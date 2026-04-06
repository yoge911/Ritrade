import asyncio
import json
import os

import redis
from nicegui import app, background_tasks, ui

from market_data.channels import EXECUTION_DASHBOARD_UPDATES_CHANNEL
from execute.trade.dashboard_state import (
    build_manual_order_command,
    build_trailing_stop_command,
    format_metric,
    format_pnl,
    format_price,
    is_positive_signal,
    latest_activity_snapshot as shared_latest_activity_snapshot,
    latest_signal_rows as shared_latest_signal_rows,
    load_status as shared_load_status,
    load_tickers as shared_load_tickers,
    pinned_tickers as shared_pinned_tickers,
    pnl_class,
    publish_command as shared_publish_command,
    score_class,
)


REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
COMMAND_CHANNEL = 'execution_commands'
PINNED_SET_KEY = 'execution_pinned_tickers'

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

CSS_PATH = os.path.join(os.path.dirname(__file__), 'dashboard.css')
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'tickers_config.json',
)


def load_tickers() -> list[str]:
    return shared_load_tickers(CONFIG_PATH)


def load_json(key: str, limit: int = 60) -> list[dict]:
    return json.loads(redis_client.get(key) or '[]')[:limit]


def load_status(ticker: str) -> dict:
    return shared_load_status(redis_client, ticker)


def pinned_tickers() -> list[str]:
    return shared_pinned_tickers(redis_client)


def publish_command(action: str, ticker: str, **extra) -> None:
    shared_publish_command(redis_client, action, ticker, **extra)


def latest_activity_snapshot(ticker: str) -> dict:
    return shared_latest_activity_snapshot(redis_client, ticker)


def latest_minute_snapshot(ticker: str) -> dict:
    minute = load_json(f'{ticker}_minute_logs', limit=60)
    return minute[-1] if minute else {}


def latest_signal_rows(tickers: list[str]) -> list[dict]:
    return shared_latest_signal_rows(redis_client, tickers)


def send_trailing_stop(ticker: str, status: dict) -> None:
    payload, error = build_trailing_stop_command(ticker, status.get('live_price'), status.get('position'))
    if error:
        ui.notify(error, color='warning')
        return

    publish_command(payload['action'], ticker, stop_price=payload['stop_price'])
    ui.notify(f'Trailing stop nudged for {ticker.upper()} at {payload["stop_price"]}.', color='positive')


class DashboardPushSubscriber:
    def __init__(self, channel: str, refresh_callback) -> None:
        self.channel = channel
        self.refresh_callback = refresh_callback
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        self.pubsub: redis.client.PubSub | None = None
        self.task: asyncio.Task | None = None
        self.running = False

    def startup(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = background_tasks.create(self.run(), name=f'{self.channel}_listener')

    async def shutdown(self) -> None:
        self.running = False
        if self.pubsub is not None:
            self.pubsub.close()
        if self.task is not None:
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def run(self) -> None:
        try:
            while self.running:
                try:
                    await self.listen()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f'⚠️ Execution dashboard listener error on {self.channel}: {exc}')
                    await asyncio.sleep(1.0)
        finally:
            if self.pubsub is not None:
                self.pubsub.close()
                self.pubsub = None

    async def listen(self) -> None:
        self.pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(self.channel)
        try:
            while self.running:
                message = self.pubsub.get_message(timeout=1.0)
                if message and message.get('type') == 'message':
                    try:
                        self.refresh_callback()
                    except Exception as exc:
                        print(f'⚠️ Execution dashboard refresh failed on {self.channel}: {exc}')
                await asyncio.sleep(0.05)
        finally:
            if self.pubsub is not None:
                self.pubsub.close()
                self.pubsub = None


def handle_order(ticker: str, side: str, status: dict) -> None:
    payload, error = build_manual_order_command(ticker, side, status.get('live_price'))
    if error:
        ui.notify(error, color='warning')
        return

    publish_command(
        payload['action'],
        ticker,
        side=payload['side'],
        limit_price=payload['limit_price'],
        initiated_by=payload['initiated_by'],
        control_mode=payload['control_mode'],
    )
    ui.notify(f'{side.upper()} limit submitted for {ticker.upper()}.', color='positive')


@ui.refreshable
def render_pinned_tickers_section() -> None:
    current_pinned = pinned_tickers()

    ui.label('Pinned Tickers').classes('section-title')
    if not current_pinned:
        ui.label('Pin a ticker from Signals to start live execution tracking.').classes('empty-state')
        return

    with ui.row().classes('widget-row'):
        for ticker in current_pinned:
            status = load_status(ticker)
            state = status.get('state', 'idle')
            control = status.get('control_mode', 'manual').upper()
            activity = latest_activity_snapshot(ticker)
            score = activity.get('activity_score')
            qualified = activity.get('is_qualified_activity')

            with ui.element('div').classes('widget-card'):
                with ui.row().classes('w-full items-start justify-between widget-header'):
                    with ui.column().classes('gap-0'):
                        ui.label(ticker.upper()).classes('widget-title')
                        ui.label(f'{state.upper()} · {control}').classes('widget-meta')
                    ui.label('HOT' if qualified else 'WATCH').classes(
                        f'widget-badge {"widget-badge-hot" if qualified else "widget-badge-muted"}',
                    )

                with ui.row().classes('w-full items-end justify-between gap-3 widget-price-row'):
                    with ui.column().classes('gap-1'):
                        ui.label('Live Price').classes('mini-label')
                        ui.label(format_price(status.get('live_price'))).classes('widget-price')
                    with ui.column().classes('gap-1 text-right'):
                        ui.label('P&L').classes('mini-label')
                        ui.label(format_pnl(status.get('pnl'))).classes(
                            f'widget-pnl {pnl_class(status.get("pnl"))}',
                        )

                with ui.row().classes('w-full widget-metrics'):
                    with ui.element('div').classes('widget-metric'):
                        ui.label('Entry').classes('mini-label')
                        ui.label(format_price(status.get('entry_price'))).classes('mini-value')
                    with ui.element('div').classes('widget-metric'):
                        ui.label('Stop').classes('mini-label')
                        ui.label(format_price(status.get('stop_price'))).classes('mini-value')
                    with ui.element('div').classes('widget-metric'):
                        ui.label('Score').classes('mini-label')
                        score_text = '—' if score in (None, '') else f'{float(score):.2f}'
                        ui.label(score_text).classes(f'mini-value {score_class(score)}')

                with ui.row().classes('w-full widget-actions'):
                    ui.button(
                        'Buy',
                        on_click=lambda t=ticker, s=status: handle_order(t, 'long', s),
                    ).classes('btn-buy widget-btn')
                    ui.button(
                        'Sell',
                        on_click=lambda t=ticker, s=status: handle_order(t, 'short', s),
                    ).classes('btn-sell widget-btn')
                    ui.button(
                        'Trail',
                        on_click=lambda t=ticker, s=status: send_trailing_stop(t, s),
                    ).classes('btn-secondary widget-btn')
                    ui.button(
                        'Close',
                        on_click=lambda t=ticker: publish_command('close_position', t),
                    ).classes('btn-ghost widget-btn')

                with ui.row().classes('w-full widget-footer'):
                    ui.label(f'Zone {status.get("zone", "Flat")}').classes('widget-footnote')
                    ui.label(
                        f'Last {activity.get("timestamp", status.get("last_update", "—"))}',
                    ).classes('widget-footnote')


@ui.refreshable
def render_activity_snapshots_panel(tickers: list[str]) -> None:
    rows = latest_signal_rows(tickers)
    with ui.element('div').classes('live-table'):
        with ui.element('div').classes('live-table-header'):
            for label in ['Ticker', 'Time', 'Score', 'Qualified', 'Trades', 'Volume', 'WAP', 'Slope', 'Action']:
                ui.label(label).classes('live-head-cell')

        for row in rows:
            pin_action = 'unpin_ticker' if row['is_pinned'] else 'pin_ticker'
            pin_label = 'Unpin' if row['is_pinned'] else 'Pin'
            score = row.get('activity_score')
            score_text = '—' if score is None else f'{float(score):.2f}'
            row_classes = 'live-table-row positive-row' if is_positive_signal(row) else 'live-table-row'

            with ui.element('div').classes(row_classes):
                ui.label(row['ticker']).classes('live-cell live-cell-strong')
                ui.label(row.get('timestamp') or '—').classes('live-cell mono-cell')
                ui.label(score_text).classes(f'live-cell mono-cell {score_class(row["activity_score"])}')
                ui.label(row['qualified']).classes(
                    f'live-cell mono-cell {"authentic-yes" if row["qualified"] == "Yes" else "authentic-no"}',
                )
                ui.label(format_metric(row['trades'], 0)).classes('live-cell mono-cell')
                ui.label(format_metric(row['volume'])).classes('live-cell mono-cell')
                ui.label(format_metric(row['wap'])).classes('live-cell mono-cell')
                ui.label(format_metric(row['slope'])).classes('live-cell mono-cell')
                ui.button(
                    pin_label,
                    on_click=lambda t=row['ticker'].lower(), a=pin_action: publish_command(a, t),
                ).classes(
                    'table-action-btn btn-ghost' if row['is_pinned'] else 'table-action-btn btn-secondary',
                )


@ui.refreshable
def render_minute_snapshots_panel(tickers: list[str]) -> None:
    rows = latest_signal_rows(tickers)

    with ui.element('div').classes('live-table'):
        with ui.element('div').classes('live-table-header minute-table-header'):
            for label in ['Ticker', '1m Time', 'Trades', 'Volume', 'Avg Price', '20s Score', 'Signal', 'Action']:
                ui.label(label).classes('live-head-cell')

        for row in rows:
            pin_action = 'unpin_ticker' if row['is_pinned'] else 'pin_ticker'
            pin_label = 'Unpin' if row['is_pinned'] else 'Pin'
            score = row.get('activity_score')
            score_text = '—' if score is None else f'{float(score):.2f}'
            signal_text = 'Positive' if is_positive_signal(row) else 'Watch'
            row_classes = 'live-table-row positive-row minute-row' if is_positive_signal(row) else 'live-table-row minute-row'

            with ui.element('div').classes(row_classes):
                ui.label(row['ticker']).classes('live-cell live-cell-strong')
                ui.label(row.get('minute_timestamp') or '—').classes('live-cell mono-cell')
                ui.label(format_metric(row['minute_trades'], 0)).classes('live-cell mono-cell')
                ui.label(format_metric(row['minute_volume'])).classes('live-cell mono-cell')
                ui.label(format_metric(row['minute_avg_price'])).classes('live-cell mono-cell')
                ui.label(score_text).classes(f'live-cell mono-cell {score_class(row["activity_score"])}')
                ui.label(signal_text).classes(
                    f'live-cell mono-cell {"authentic-yes" if is_positive_signal(row) else "authentic-no"}',
                )
                ui.button(
                    pin_label,
                    on_click=lambda t=row['ticker'].lower(), a=pin_action: publish_command(a, t),
                ).classes(
                    'table-action-btn btn-ghost' if row['is_pinned'] else 'table-action-btn btn-secondary',
                )


def refresh_execution_dashboard(tickers: list[str]) -> None:
    render_pinned_tickers_section.refresh()
    render_activity_snapshots_panel.refresh(tickers)
    render_minute_snapshots_panel.refresh(tickers)


execution_subscriber = DashboardPushSubscriber(
    EXECUTION_DASHBOARD_UPDATES_CHANNEL,
    refresh_callback=lambda: refresh_execution_dashboard(load_tickers()),
)

app.on_startup(execution_subscriber.startup)
app.on_shutdown(execution_subscriber.shutdown)


@ui.page('/')
def main():
    tickers = load_tickers()

    with open(CSS_PATH) as f:
        ui.add_head_html(f'<style>{f.read()}</style>')

    with ui.element('div').classes('page-shell'):
        with ui.element('div').classes('hero-panel'):
            ui.label('Ritrade').classes('hero-title')

        with ui.column().classes('w-full gap-5 content-shell'):
            with ui.column().classes('gap-3'):
                render_pinned_tickers_section()

            with ui.column().classes('glass-panel gap-4 full-width-panel'):
                with ui.row().classes('items-center justify-between'):
                    ui.label('Monitoring Snapshots').classes('panel-title')
                    ui.label('full-width live feed').classes('panel-caption')

                with ui.tabs().props('align=left dense no-caps').classes('snapshot-tabs w-full') as tabs:
                    tab_activity = ui.tab('20s Snapshots')
                    tab_minute = ui.tab('1m Signal Snapshots')

                with ui.tab_panels(tabs, value=tab_activity).classes('w-full snapshot-panels'):
                    with ui.tab_panel(tab_activity).classes('w-full'):
                        render_activity_snapshots_panel(tickers)

                    with ui.tab_panel(tab_minute).classes('w-full'):
                        render_minute_snapshots_panel(tickers)


ui.run(title='Ritrade', dark=True, favicon='📈', port=8080, reload=False)
