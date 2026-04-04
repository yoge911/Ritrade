import json
import os
import sys
from datetime import datetime

import redis
from nicegui import ui

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from market_data.channels import activity_snapshots_key, minute_logs_key, rolling_metrics_key

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

CSS_PATH = os.path.join(os.path.dirname(__file__), 'dashboard.css')
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tickers_config.json')


def load(key: str, limit: int = 60) -> list[dict]:
    """Read a JSON list from Redis, returning at most `limit` entries."""
    return json.loads(redis_client.get(key) or '[]')[:limit]


def latest(key: str) -> dict:
    """Return the latest row from a Redis JSON list, or an empty dict."""
    rows = load(key, limit=60)
    return rows[-1] if rows else {}


def load_tickers() -> list[str]:
    with open(CONFIG_PATH, 'r') as config_file:
        return [item['ticker'].lower() for item in json.load(config_file)]


def format_metric(value: object, digits: int = 2) -> str:
    if value in (None, ''):
        return '—'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return str(value)
    return f'{number:.{digits}f}'


def format_duration_ms(value: object) -> str:
    if value in (None, ''):
        return '—'
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f'{ms / 1000:.0f}s'


def signal_label(row: dict) -> str:
    if row.get('is_qualified_activity'):
        return 'Qualified'
    score = row.get('activity_score')
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        return 'Watching'
    if numeric_score >= 0.3:
        return 'Developing'
    return 'Quiet'


def signal_class(row: dict) -> str:
    if row.get('is_qualified_activity'):
        return 'signal-hot'
    score = row.get('activity_score')
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        return 'signal-cold'
    if numeric_score >= 0.3:
        return 'signal-warm'
    return 'signal-cold'


def build_ticker_snapshot(ticker: str) -> dict:
    rolling = latest(rolling_metrics_key(ticker))
    setup = latest(activity_snapshots_key(ticker))
    minute = latest(minute_logs_key(ticker))
    return {
        'ticker': ticker.upper(),
        'rolling': rolling,
        'setup': setup,
        'minute': minute,
        'signal': signal_label(rolling),
        'signal_class': signal_class(rolling),
    }


def build_overview_rows(tickers: list[str]) -> list[dict]:
    return [build_ticker_snapshot(ticker) for ticker in tickers]


def build_summary_metrics(overview_rows: list[dict], trap_rows: list[dict], minute_rows: list[dict]) -> list[tuple[str, str, str]]:
    qualified_now = sum(1 for row in overview_rows if row['rolling'].get('is_qualified_activity'))
    latest_setup_time = trap_rows[-1].get('timestamp', '—') if trap_rows else '—'
    latest_setup_duration = format_duration_ms(trap_rows[-1].get('qualification_duration_ms')) if trap_rows else '—'
    return [
        ('Tracked Tickers', str(len(overview_rows)), 'Tickers loaded from config and monitored through Redis'),
        ('Qualified Now', str(qualified_now), 'Tickers whose latest rolling window currently passes qualification'),
        ('Latest Setup', latest_setup_time, f'Last finalized setup snapshot, duration {latest_setup_duration}'),
    ]


def rolling_table_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in reversed(rows):
        output.append({
            'ticker': str(row.get('ticker', '—')).upper(),
            'time': row.get('timestamp', '—'),
            'signal': signal_label(row),
            'score': format_metric(row.get('activity_score')),
            'trades': format_metric(row.get('trades'), 0),
            'volume': format_metric(row.get('volume'), 3),
            'wap': format_metric(row.get('wap'), 5),
            'std_dev': format_metric(row.get('std_dev'), 5),
            'slope': format_metric(row.get('slope'), 5),
        })
    return output


def setup_table_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in reversed(rows):
        output.append({
            'ticker': str(row.get('ticker', '—')).upper(),
            'setup_start': row.get('setup_start_time', '—'),
            'setup_end': row.get('setup_end_time', row.get('timestamp', '—')),
            'duration': format_duration_ms(row.get('qualification_duration_ms')),
            'signal': signal_label(row),
            'score': format_metric(row.get('activity_score')),
            'trades': format_metric(row.get('trades'), 0),
            'volume': format_metric(row.get('volume'), 3),
            'trigger': row.get('trigger_reason', '—'),
        })
    return output


def minute_table_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in reversed(rows):
        output.append({
            'ticker': str(row.get('ticker', '—')).upper(),
            'minute': row.get('timestamp', '—'),
            'trades': format_metric(row.get('trades'), 0),
            'volume': format_metric(row.get('volume'), 3),
            'avg_price': format_metric(row.get('avg_price'), 5),
        })
    return output


ROLLING_COLUMNS = [
    {'name': 'ticker', 'label': 'Ticker', 'field': 'ticker', 'align': 'left'},
    {'name': 'time', 'label': 'Time', 'field': 'time', 'align': 'left'},
    {'name': 'signal', 'label': 'Signal', 'field': 'signal', 'align': 'left'},
    {'name': 'score', 'label': 'Score', 'field': 'score', 'align': 'right'},
    {'name': 'trades', 'label': 'Trades', 'field': 'trades', 'align': 'right'},
    {'name': 'volume', 'label': 'Volume', 'field': 'volume', 'align': 'right'},
    {'name': 'wap', 'label': 'WAP', 'field': 'wap', 'align': 'right'},
    {'name': 'std_dev', 'label': 'Std Dev', 'field': 'std_dev', 'align': 'right'},
    {'name': 'slope', 'label': 'Slope', 'field': 'slope', 'align': 'right'},
]

SETUP_COLUMNS = [
    {'name': 'ticker', 'label': 'Ticker', 'field': 'ticker', 'align': 'left'},
    {'name': 'setup_start', 'label': 'Start', 'field': 'setup_start', 'align': 'left'},
    {'name': 'setup_end', 'label': 'End', 'field': 'setup_end', 'align': 'left'},
    {'name': 'duration', 'label': 'Window', 'field': 'duration', 'align': 'right'},
    {'name': 'signal', 'label': 'Signal', 'field': 'signal', 'align': 'left'},
    {'name': 'score', 'label': 'Score', 'field': 'score', 'align': 'right'},
    {'name': 'trades', 'label': 'Trades', 'field': 'trades', 'align': 'right'},
    {'name': 'volume', 'label': 'Volume', 'field': 'volume', 'align': 'right'},
    {'name': 'trigger', 'label': 'Trigger', 'field': 'trigger', 'align': 'left'},
]

MINUTE_COLUMNS = [
    {'name': 'ticker', 'label': 'Ticker', 'field': 'ticker', 'align': 'left'},
    {'name': 'minute', 'label': 'Minute', 'field': 'minute', 'align': 'left'},
    {'name': 'trades', 'label': 'Trades', 'field': 'trades', 'align': 'right'},
    {'name': 'volume', 'label': 'Volume', 'field': 'volume', 'align': 'right'},
    {'name': 'avg_price', 'label': 'Avg Price', 'field': 'avg_price', 'align': 'right'},
]


@ui.page('/')
def main():
    tickers = load_tickers()

    with open(CSS_PATH) as css_file:
        ui.add_head_html(f'<style>{css_file.read()}</style>')

    with ui.element('div').classes('page-shell'):
        with ui.element('div').classes('hero-panel'):
            with ui.row().classes('items-center justify-between w-full'):
                with ui.column().classes('gap-1'):
                    ui.label('Ritrade Monitor').classes('hero-title')
                    ui.label('Rolling trade diagnostics, finalized setup snapshots, and minute rollover summaries').classes('hero-subtitle')
                last_updated = ui.label('Updated —').classes('header-timestamp')

        with ui.column().classes('content-shell w-full gap-5'):
            with ui.row().classes('metric-grid'):
                summary_container = ui.row().classes('metric-grid w-full')

            with ui.column().classes('gap-3'):
                ui.label('Per-Ticker Snapshot').classes('section-title')
                overview_empty = ui.label('Waiting for rolling metrics from activity_monitor…').classes('empty-state')
                overview_container = ui.element('div').classes('ticker-grid w-full')

            with ui.column().classes('glass-panel gap-4 full-width-panel'):
                with ui.row().classes('items-center justify-between'):
                    ui.label('Monitor Feeds').classes('panel-title')
                    ui.label('Latest rows shown first').classes('panel-caption')

                with ui.tabs().props('align=left dense no-caps').classes('w-full') as tabs:
                    tab_rolling = ui.tab('Rolling 10s Diagnostics')
                    tab_setup = ui.tab('Finalized Setup Snapshots')
                    tab_minute = ui.tab('Minute Rollover Summary')

                with ui.tab_panels(tabs, value=tab_rolling).classes('w-full snapshot-panels'):
                    with ui.tab_panel(tab_rolling).classes('w-full'):
                        rolling_empty = ui.label('Waiting for rolling diagnostics…').classes('empty-state')
                        rolling_table = ui.table(columns=ROLLING_COLUMNS, rows=[], row_key='time').classes('data-table w-full')
                    with ui.tab_panel(tab_setup).classes('w-full'):
                        setup_empty = ui.label('Waiting for finalized setup snapshots…').classes('empty-state')
                        setup_table = ui.table(columns=SETUP_COLUMNS, rows=[], row_key='setup_end').classes('data-table w-full')
                    with ui.tab_panel(tab_minute).classes('w-full'):
                        minute_empty = ui.label('Waiting for minute rollover summaries…').classes('empty-state')
                        minute_table = ui.table(columns=MINUTE_COLUMNS, rows=[], row_key='minute').classes('data-table w-full')

    def render_summary_cards(metrics: list[tuple[str, str, str]]) -> None:
        summary_container.clear()
        with summary_container:
            for label, value, note in metrics:
                with ui.element('div').classes('metric-card'):
                    ui.label(label).classes('metric-label')
                    ui.label(value).classes('metric-value')
                    ui.label(note).classes('metric-note')

    def render_ticker_cards(rows: list[dict]) -> None:
        overview_container.clear()
        overview_empty.set_visibility(not rows)
        if not rows:
            return

        with overview_container:
            for row in rows:
                rolling = row['rolling']
                setup = row['setup']
                minute = row['minute']

                with ui.element('div').classes('ticker-card'):
                    with ui.row().classes('items-start justify-between w-full'):
                        with ui.column().classes('gap-0'):
                            ui.label(row['ticker']).classes('ticker-title')
                            ui.label('Latest rolling state').classes('ticker-subtitle')
                        ui.label(row['signal']).classes(f'status-badge {row["signal_class"]}')

                    with ui.row().classes('ticker-metrics'):
                        with ui.element('div').classes('ticker-metric'):
                            ui.label('Live Price').classes('mini-label')
                            ui.label(format_metric(rolling.get('live_price'), 2)).classes('mini-value')
                        with ui.element('div').classes('ticker-metric'):
                            ui.label('Score').classes('mini-label')
                            ui.label(format_metric(rolling.get('activity_score'))).classes('mini-value')
                        with ui.element('div').classes('ticker-metric'):
                            ui.label('Trades').classes('mini-label')
                            ui.label(format_metric(rolling.get('trades'), 0)).classes('mini-value')
                        with ui.element('div').classes('ticker-metric'):
                            ui.label('Volume').classes('mini-label')
                            ui.label(format_metric(rolling.get('volume'), 3)).classes('mini-value')

                    with ui.column().classes('ticker-detail-list'):
                        ui.label(
                            f'Rolling: {rolling.get("timestamp", "—")} · WAP {format_metric(rolling.get("wap"), 5)} · Slope {format_metric(rolling.get("slope"), 5)}'
                        ).classes('ticker-detail')
                        ui.label(
                            f'Latest setup: {setup.get("setup_start_time", "—")} -> {setup.get("setup_end_time", "—")} · Score {format_metric(setup.get("activity_score"))}'
                        ).classes('ticker-detail')
                        ui.label(
                            f'Minute summary: {minute.get("timestamp", "—")} · Trades {format_metric(minute.get("trades"), 0)} · Volume {format_metric(minute.get("volume"), 3)}'
                        ).classes('ticker-detail')

    def update_ui() -> None:
        rolling_rows = load('rolling_metrics_logs')
        setup_rows = load('trap_logs')
        minute_rows = load('minute_logs')
        overview_rows = build_overview_rows(tickers)

        render_summary_cards(build_summary_metrics(overview_rows, setup_rows, minute_rows))
        render_ticker_cards(overview_rows)

        rolling_table.rows = rolling_table_rows(rolling_rows)
        rolling_empty.set_visibility(not rolling_table.rows)
        rolling_table.set_visibility(bool(rolling_table.rows))
        rolling_table.update()

        setup_table.rows = setup_table_rows(setup_rows)
        setup_empty.set_visibility(not setup_table.rows)
        setup_table.set_visibility(bool(setup_table.rows))
        setup_table.update()

        minute_table.rows = minute_table_rows(minute_rows)
        minute_empty.set_visibility(not minute_table.rows)
        minute_table.set_visibility(bool(minute_table.rows))
        minute_table.update()

        last_updated.text = f'Updated {datetime.now().strftime("%H:%M:%S")}'

    ui.timer(2.0, update_ui)


ui.run(title='Ritrade Monitor', dark=True, favicon='📊', port=8081, reload=False)
