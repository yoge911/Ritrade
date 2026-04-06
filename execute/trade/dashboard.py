import asyncio
import json
import os

import redis
from nicegui import app, background_tasks, ui

from market_data.channels import EXECUTION_DASHBOARD_UPDATES_CHANNEL


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
    with open(CONFIG_PATH, 'r') as f:
        return [item['ticker'].lower() for item in json.load(f)]


def load_json(key: str, limit: int = 60) -> list[dict]:
    return json.loads(redis_client.get(key) or '[]')[:limit]


def load_status(ticker: str) -> dict:
    return redis_client.hgetall(f'{ticker}_status')


def pinned_tickers() -> list[str]:
    return sorted(redis_client.smembers(PINNED_SET_KEY))


def publish_command(action: str, ticker: str, **extra) -> None:
    payload = {'action': action, 'ticker': ticker}
    payload.update(extra)
    redis_client.publish(COMMAND_CHANNEL, json.dumps(payload))


def latest_activity_snapshot(ticker: str) -> dict:
    snapshot = load_json(f'{ticker}_activity_snapshots', limit=60)
    return snapshot[-1] if snapshot else {}


def latest_minute_snapshot(ticker: str) -> dict:
    minute = load_json(f'{ticker}_minute_logs', limit=60)
    return minute[-1] if minute else {}


def latest_signal_rows(tickers: list[str]) -> list[dict]:
    rows = []
    pinned = set(pinned_tickers())

    for ticker in tickers:
        activity = latest_activity_snapshot(ticker)
        minute = latest_minute_snapshot(ticker)
        rows.append({
            'ticker': ticker.upper(),
            'timestamp': activity.get('timestamp', '—'),
            'qualified': 'Yes' if activity.get('is_qualified_activity') else 'No',
            'activity_score': activity.get('activity_score', '—'),
            'trades': activity.get('trades', '—'),
            'volume': activity.get('volume', '—'),
            'wap': activity.get('wap', '—'),
            'std_dev': activity.get('std_dev', '—'),
            'slope': activity.get('slope', '—'),
            'minute_timestamp': minute.get('timestamp', '—'),
            'minute_trades': minute.get('trades', '—'),
            'minute_volume': minute.get('volume', '—'),
            'minute_avg_price': minute.get('avg_price', '—'),
            'is_pinned': ticker in pinned,
        })

    rows.sort(
        key=lambda row: row['activity_score'] if isinstance(row['activity_score'], (int, float)) else -1,
        reverse=True,
    )
    return rows


def parse_float(value: str | float | int | None) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_price(value: str | float | None) -> str:
    number = parse_float(value)
    return '—' if number is None else f'${number:.2f}'


def format_pnl(value: str | float | None) -> str:
    number = parse_float(value)
    if number is None:
        return '—'
    sign = '+' if number >= 0 else ''
    return f'{sign}{number:.2f}'


def format_metric(value: str | float | int | None, digits: int = 2) -> str:
    if value in (None, ''):
        return '—'
    parsed = parse_float(value)
    if parsed is None:
        return str(value)
    return f'{parsed:.{digits}f}'


def pnl_class(value: str | float | None) -> str:
    number = parse_float(value)
    if number is None:
        return 'neutral'
    if number > 0:
        return 'profit'
    if number < 0:
        return 'loss'
    return 'neutral'


def score_class(value: object) -> str:
    if not isinstance(value, (int, float)):
        return 'signal-cold'
    if value >= 0.6:
        return 'signal-hot'
    if value >= 0.3:
        return 'signal-warm'
    return 'signal-cold'


def is_positive_signal(row: dict) -> bool:
    score = row.get('activity_score')
    return row.get('qualified') == 'Yes' or (isinstance(score, (int, float)) and score >= 0.3)


def send_trailing_stop(ticker: str, status: dict) -> None:
    live_price = parse_float(status.get('live_price'))
    position = status.get('position')
    if live_price is None or position not in {'long', 'short'}:
        ui.notify(f'{ticker.upper()} needs an active trade and live price for trailing stop.', color='warning')
        return

    trail_gap = 0.0015
    stop_price = live_price * (1 - trail_gap) if position == 'long' else live_price * (1 + trail_gap)
    rounded_stop = round(stop_price, 2)
    publish_command('modify_stop', ticker, stop_price=rounded_stop)
    ui.notify(f'Trailing stop nudged for {ticker.upper()} at {rounded_stop}.', color='positive')


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
        self.task = background_tasks.create(self.listen(), name=f'{self.channel}_listener')

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

    async def listen(self) -> None:
        self.pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(self.channel)
        try:
            while self.running:
                message = self.pubsub.get_message(timeout=1.0)
                if message and message.get('type') == 'message':
                    self.refresh_callback()
                await asyncio.sleep(0.05)
        finally:
            if self.pubsub is not None:
                self.pubsub.close()
                self.pubsub = None


def handle_order(ticker: str, side: str, status: dict) -> None:
    live_price = status.get('live_price')
    if not live_price:
        ui.notify(f'{ticker.upper()} has no live price yet.', color='warning')
        return

    publish_command(
        'place_limit_order',
        ticker,
        side=side,
        limit_price=live_price,
        initiated_by='manual',
        control_mode='manual',
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
            score_text = '—' if row['activity_score'] == '—' else f'{float(row["activity_score"]):.2f}'
            row_classes = 'live-table-row positive-row' if is_positive_signal(row) else 'live-table-row'

            with ui.element('div').classes(row_classes):
                ui.label(row['ticker']).classes('live-cell live-cell-strong')
                ui.label(row['timestamp']).classes('live-cell mono-cell')
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
            score_text = '—' if row['activity_score'] == '—' else f'{float(row["activity_score"]):.2f}'
            signal_text = 'Positive' if is_positive_signal(row) else 'Watch'
            row_classes = 'live-table-row positive-row minute-row' if is_positive_signal(row) else 'live-table-row minute-row'

            with ui.element('div').classes(row_classes):
                ui.label(row['ticker']).classes('live-cell live-cell-strong')
                ui.label(row['minute_timestamp']).classes('live-cell mono-cell')
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
