"""Render the monitor dashboard, including calibration run browsing and activation controls."""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import redis
from nicegui import app, background_tasks, ui

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from market_data.channels import (
    MARKET_DATA_UPDATES_CHANNEL,
    MONITOR_DASHBOARD_UPDATES_CHANNEL,
    activity_snapshots_key,
    latest_trade_event_key,
    minute_logs_key,
    rolling_metrics_key,
)
from monitor.calibration_store import (
    ActiveCalibrationState,
    CalibrationSnapshot,
    activate_runtime_calibration_snapshot,
    isoformat_utc,
    load_active_calibration_state,
    resolve_active_calibration_snapshot,
    set_activation_mode,
)
from monitor.calibrate_activity import (
    ArchivePeriod,
    DEFAULT_ARCHIVE_ROOT,
    DEFAULT_CALIBRATION_PATH,
    DEFAULT_LOWER_PERCENTILE,
    DEFAULT_MIN_SAMPLE_COUNT,
    DEFAULT_SAMPLING_INTERVAL_MS,
    DEFAULT_UPPER_PERCENTILE,
    archive_periods,
    compute_archive_period_snapshot_for_hours,
    compute_latest_archive_period_snapshot_for_hours,
)
from monitor.activity_metrics import ROLLING_WINDOW_MS

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
    """Load the configured ticker symbols used throughout the monitor dashboard."""

    with open(CONFIG_PATH, 'r') as config_file:
        return [item['ticker'].lower() for item in json.load(config_file)]


def load_latest_trade(ticker: str) -> dict:
    """Load the latest raw trade snapshot for a ticker from Redis."""

    payload = redis_client.get(latest_trade_event_key(ticker))
    return json.loads(payload) if payload else {}


def format_metric(value: object, digits: int = 2) -> str:
    """Format numeric dashboard metrics while preserving non-numeric placeholders."""

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
    """Render millisecond durations in seconds for compact UI display."""

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
    """Assemble the current per-ticker monitor card payload from Redis-backed sources."""

    rolling = latest(rolling_metrics_key(ticker))
    setup = latest(activity_snapshots_key(ticker))
    minute = latest(minute_logs_key(ticker))
    latest_trade = load_latest_trade(ticker)
    return {
        'ticker': ticker.upper(),
        'rolling': rolling,
        'latest_trade': latest_trade,
        'setup': setup,
        'minute': minute,
        'signal': signal_label(rolling),
        'signal_class': signal_class(rolling),
    }


def build_overview_rows(tickers: list[str]) -> list[dict]:
    """Build all ticker overview cards in config order."""

    return [build_ticker_snapshot(ticker) for ticker in tickers]



def rolling_table_rows(rows: list[dict]) -> list[dict]:
    return [{
        'ticker': str(row.get('ticker', '—')).upper(),
        'time': row.get('timestamp', '—'),
        'signal': signal_label(row),
        'score': format_metric(row.get('activity_score')),
        'trades': format_metric(row.get('trades'), 0),
        'volume': format_metric(row.get('volume'), 3),
        'wap': format_metric(row.get('wap'), 5),
        'std_dev': format_metric(row.get('std_dev'), 5),
        'slope': format_metric(row.get('slope'), 5),
    } for row in reversed(rows)]


def setup_table_rows(rows: list[dict]) -> list[dict]:
    return [{
        'ticker': str(row.get('ticker', '—')).upper(),
        'setup_start': row.get('setup_start_time', '—'),
        'setup_end': row.get('setup_end_time', row.get('timestamp', '—')),
        'duration': format_duration_ms(row.get('qualification_duration_ms')),
        'signal': signal_label(row),
        'score': format_metric(row.get('activity_score')),
        'trades': format_metric(row.get('trades'), 0),
        'volume': format_metric(row.get('volume'), 3),
        'trigger': row.get('trigger_reason', '—'),
    } for row in reversed(rows)]


def minute_table_rows(rows: list[dict]) -> list[dict]:
    return [{
        'ticker': str(row.get('ticker', '—')).upper(),
        'minute': row.get('timestamp', '—'),
        'trades': format_metric(row.get('trades'), 0),
        'volume': format_metric(row.get('volume'), 3),
        'avg_price': format_metric(row.get('avg_price'), 5),
    } for row in reversed(rows)]


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


calibration_panel_state = {
    'selected_period_id': None,
    'archive_hours': 2,
    'preview_snapshot': None,
    'preview_period_id': None,
    'preview_archive_hours': None,
    'notice': '',
    'compute_notice': '',
    'compute_in_progress': False,
    'last_started_at': None,
}

ARCHIVE_HOURS_OPTIONS = {
    1: '1 hour',
    2: '2 hours',
    3: '3 hours',
    4: '4 hours',
    5: '5 hours',
    6: '6 hours',
}


def format_clock_time(value: datetime) -> str:
    """Format a timezone-aware datetime for the calibration panel."""

    return value.astimezone().strftime('%Y-%m-%d %H:%M:%S')


def format_event_time_ms(value: int | None) -> str:
    """Format an event timestamp stored as epoch milliseconds."""

    if value is None:
        return '—'
    return format_clock_time(datetime.fromtimestamp(value / 1000))


def format_iso_time(value: str | None) -> str:
    """Format a stored UTC ISO timestamp for UI display."""

    if not value:
        return '—'
    return format_clock_time(datetime.fromisoformat(value.replace('Z', '+00:00')))


def calibration_period_summary(snapshot: CalibrationSnapshot) -> tuple[str, str]:
    """Return the earliest and latest sampled event times represented by a run."""

    first_times = [entry.source.first_event_time_ms for entry in snapshot.tickers if entry.source.first_event_time_ms is not None]
    last_times = [entry.source.last_event_time_ms for entry in snapshot.tickers if entry.source.last_event_time_ms is not None]
    return (
        format_event_time_ms(min(first_times)) if first_times else '—',
        format_event_time_ms(max(last_times)) if last_times else '—',
    )


def load_archive_periods() -> list[ArchivePeriod]:
    """Return one selector option per hourly archive file across the configured tickers."""

    tickers = load_tickers()
    if not tickers:
        return []
    return archive_periods(Path(DEFAULT_ARCHIVE_ROOT), tickers)


def build_archive_period_option_label(period: ArchivePeriod) -> str:
    """Format one archive-backed selector option."""

    label = format_clock_time(period.nominal_end_time)
    if period.effective_end_time < period.nominal_end_time:
        return f'{label} [PARTIAL]'
    return label


def resolve_selected_archive_period(periods: list[ArchivePeriod], active_state: ActiveCalibrationState | None) -> ArchivePeriod | None:
    """Resolve the currently selected archive period from UI state and available archive files."""

    selected_period_id = calibration_panel_state.get('selected_period_id')
    available_ids = {period.period_id for period in periods}
    if selected_period_id not in available_ids:
        selected_period_id = None

    if selected_period_id is None and active_state and active_state.active_archive_period_id in available_ids:
        selected_period_id = active_state.active_archive_period_id
    if selected_period_id is None and periods:
        selected_period_id = periods[-1].period_id

    calibration_panel_state['selected_period_id'] = selected_period_id
    return next((period for period in periods if period.period_id == selected_period_id), None)


def matches_preview(period: ArchivePeriod | None, archive_hours: int) -> bool:
    """Return whether the in-memory preview matches the current period and hour selection."""

    return (
        period is not None
        and calibration_panel_state.get('preview_snapshot') is not None
        and calibration_panel_state.get('preview_period_id') == period.period_id
        and calibration_panel_state.get('preview_archive_hours') == archive_hours
    )


def matches_active_runtime(
    period: ArchivePeriod | None,
    archive_hours: int,
    active_state: ActiveCalibrationState | None,
    snapshot: CalibrationSnapshot | None,
) -> bool:
    """Return whether the runtime-active thresholds match the current period and hour selection."""

    if period is None or active_state is None or snapshot is None:
        return False
    if active_state.active_archive_period_id is not None:
        return (
            active_state.active_archive_period_id == period.period_id
            and active_state.active_archive_hours == archive_hours
        )
    return (
        active_state.active_run_id == period.period_id
        and bool(snapshot.tickers)
        and snapshot.tickers[0].lookback_duration_minutes == archive_hours * 60
    )


def resolve_period_by_id(periods: list[ArchivePeriod], period_id: str | None) -> ArchivePeriod | None:
    """Return the archive period matching the supplied id, if present."""

    if period_id is None:
        return None
    return next((period for period in periods if period.period_id == period_id), None)


def resolve_calibration_view_model() -> dict:
    """Resolve archive periods, selected period, preview/runtime snapshot, and notices for the panel."""

    periods = load_archive_periods()
    active_state = load_active_calibration_state()
    archive_hours = int(calibration_panel_state.get('archive_hours', 2))
    selected_period = resolve_selected_archive_period(periods, active_state)
    active_snapshot = resolve_active_calibration_snapshot()

    selected_snapshot: CalibrationSnapshot | None = None
    selected_snapshot_status: str | None = None
    displayed_period: ArchivePeriod | None = None
    displayed_archive_hours = archive_hours
    if matches_active_runtime(selected_period, archive_hours, active_state, active_snapshot):
        selected_snapshot = active_snapshot
        selected_snapshot_status = 'active'
        displayed_period = selected_period
    elif matches_preview(selected_period, archive_hours):
        selected_snapshot = calibration_panel_state.get('preview_snapshot')
        selected_snapshot_status = 'preview'
        displayed_period = selected_period
    elif calibration_panel_state.get('preview_snapshot') is not None:
        selected_snapshot = calibration_panel_state.get('preview_snapshot')
        selected_snapshot_status = 'preview'
        displayed_period = resolve_period_by_id(periods, calibration_panel_state.get('preview_period_id'))
        displayed_archive_hours = int(calibration_panel_state.get('preview_archive_hours') or archive_hours)
    elif active_snapshot is not None:
        selected_snapshot = active_snapshot
        selected_snapshot_status = 'active'
        active_period_id = (active_state.active_archive_period_id if active_state else None) or (active_state.active_run_id if active_state else None)
        displayed_period = resolve_period_by_id(periods, active_period_id)
        displayed_archive_hours = int((active_state.active_archive_hours if active_state and active_state.active_archive_hours is not None else archive_hours))

    return {
        'periods': periods,
        'active_state': active_state,
        'selected_period': selected_period,
        'selected_period_id': (selected_period.period_id if selected_period else None),
        'selected_snapshot': selected_snapshot,
        'selected_snapshot_status': selected_snapshot_status,
        'displayed_period': displayed_period,
        'displayed_archive_hours': displayed_archive_hours,
        'archive_hours': archive_hours,
        'notice': calibration_panel_state.get('notice', ''),
        'compute_notice': calibration_panel_state.get('compute_notice', ''),
        'compute_in_progress': calibration_panel_state.get('compute_in_progress', False),
        'last_started_at': calibration_panel_state.get('last_started_at'),
    }


def handle_archive_period_selection(event) -> None:
    """Update the viewed archive period without changing runtime thresholds."""

    calibration_panel_state['selected_period_id'] = event.value
    calibration_panel_state['compute_notice'] = ''
    render_calibration_panel.refresh()


def handle_activation_mode_change(event) -> None:
    """Switch between auto and manual activation modes from the dashboard."""

    mode = event.value
    archive_hours = int(calibration_panel_state.get('archive_hours', 2))
    state = set_activation_mode(mode, auto_archive_hours=archive_hours)
    if mode == 'auto':
        calibration_panel_state['notice'] = (
            f'Automatic mode enabled. Computing and activating the newest archive-backed thresholds now, then refreshing hourly using {archive_hours} hour(s).'
        )
        ui.notify('Calibration mode set to auto.', color='positive')
        background_tasks.create(
            activate_latest_archive_period_for_auto_mode(archive_hours=archive_hours),
            name='monitor_auto_archive_activation',
        )
    else:
        calibration_panel_state['notice'] = (
            'Manual mode enabled. Future calibration runs will update latest only until you activate one explicitly.'
        )
        ui.notify('Calibration mode set to manual.', color='warning')
    render_calibration_panel.refresh()


def handle_archive_hours_change(event) -> None:
    """Update the UI-selected archive-hour window used by manual calibration."""

    calibration_panel_state['archive_hours'] = int(event.value)
    calibration_panel_state['compute_notice'] = ''
    render_calibration_panel.refresh()


def _compute_selected_archive_period_snapshot() -> tuple[CalibrationSnapshot, ArchivePeriod, int]:
    """Compute thresholds for the currently selected archive period and archive-hour window."""

    tickers = load_tickers()
    if not tickers:
        raise ValueError('No tickers configured for calibration.')

    periods = load_archive_periods()
    selected_period_id = calibration_panel_state.get('selected_period_id')
    selected_period = next((period for period in periods if period.period_id == selected_period_id), None)
    if selected_period is None and periods:
        selected_period = periods[-1]
    if selected_period is None:
        raise ValueError('No archive periods found yet.')

    archive_hours = int(calibration_panel_state.get('archive_hours', 2))
    snapshot = compute_archive_period_snapshot_for_hours(
        tickers,
        archive_root=Path(DEFAULT_ARCHIVE_ROOT),
        output_path=Path(DEFAULT_CALIBRATION_PATH),
        archive_period=selected_period,
        archive_hours=archive_hours,
        sampling_interval_ms=DEFAULT_SAMPLING_INTERVAL_MS,
        lower_percentile=DEFAULT_LOWER_PERCENTILE,
        upper_percentile=DEFAULT_UPPER_PERCENTILE,
        window_ms=ROLLING_WINDOW_MS,
        min_sample_count=DEFAULT_MIN_SAMPLE_COUNT,
    )
    if not snapshot.tickers:
        raise ValueError('No thresholds could be computed for the selected archive period.')
    return snapshot, selected_period, archive_hours


def _compute_latest_archive_period_snapshot(archive_hours: int) -> tuple[CalibrationSnapshot, ArchivePeriod, int]:
    """Compute thresholds for the newest available archive period."""

    tickers = load_tickers()
    if not tickers:
        raise ValueError('No tickers configured for calibration.')

    snapshot, selected_period = compute_latest_archive_period_snapshot_for_hours(
        tickers,
        archive_root=Path(DEFAULT_ARCHIVE_ROOT),
        output_path=Path(DEFAULT_CALIBRATION_PATH),
        archive_hours=archive_hours,
        sampling_interval_ms=DEFAULT_SAMPLING_INTERVAL_MS,
        lower_percentile=DEFAULT_LOWER_PERCENTILE,
        upper_percentile=DEFAULT_UPPER_PERCENTILE,
        window_ms=ROLLING_WINDOW_MS,
        min_sample_count=DEFAULT_MIN_SAMPLE_COUNT,
    )
    return snapshot, selected_period, archive_hours


async def compute_selected_period_preview(*, show_success_notice: bool) -> tuple[CalibrationSnapshot, ArchivePeriod, int] | None:
    """Compute and cache a preview snapshot for the current period and hour selection."""

    try:
        snapshot, selected_period, archive_hours = await asyncio.to_thread(
            _compute_selected_archive_period_snapshot,
        )
    except ValueError as exc:
        calibration_panel_state['compute_notice'] = f'Compute from archive failed: {exc}'
        ui.notify(f'Compute from archive failed: {exc}', color='negative')
        return None
    except Exception as exc:
        calibration_panel_state['compute_notice'] = f'Compute from archive failed unexpectedly: {exc}'
        ui.notify(f'Compute from archive failed: {exc}', color='negative')
        return None

    calibration_panel_state['preview_snapshot'] = snapshot
    calibration_panel_state['preview_period_id'] = selected_period.period_id
    calibration_panel_state['preview_archive_hours'] = archive_hours
    calibration_panel_state['selected_period_id'] = selected_period.period_id
    calibration_panel_state['compute_notice'] = (
        f'Computed preview for archive period {build_archive_period_option_label(selected_period)} using {archive_hours} hour(s).'
    )
    if show_success_notice:
        ui.notify(
            f'Computed preview for {build_archive_period_option_label(selected_period)} using {archive_hours} hour(s).',
            color='positive',
        )
    return snapshot, selected_period, archive_hours


async def handle_calibration_activation() -> None:
    """Activate the selected archive period and archive-hour window for runtime monitoring."""

    if calibration_panel_state.get('compute_in_progress'):
        ui.notify('Calibration compute is already running.', color='warning')
        return

    periods = load_archive_periods()
    selected_period = resolve_selected_archive_period(periods, load_active_calibration_state())
    if selected_period is None:
        ui.notify('No archive period selected.', color='warning')
        return

    archive_hours = int(calibration_panel_state.get('archive_hours', 2))
    preview_ready = matches_preview(selected_period, archive_hours)

    calibration_panel_state['compute_in_progress'] = True
    calibration_panel_state['last_started_at'] = datetime.now().astimezone().isoformat()
    calibration_panel_state['compute_notice'] = 'Calibration run in progress...'
    render_calibration_panel.refresh()

    try:
        if preview_ready:
            snapshot = calibration_panel_state.get('preview_snapshot')
        else:
            computed = await compute_selected_period_preview(show_success_notice=False)
            if computed is None:
                return
            snapshot, selected_period, archive_hours = computed

        state = activate_runtime_calibration_snapshot(
            snapshot,
            archive_period_id=selected_period.period_id,
            archive_period_end=isoformat_utc(selected_period.nominal_end_time),
            archive_hours=archive_hours,
        )
        calibration_panel_state['compute_notice'] = ''
        calibration_panel_state['notice'] = (
            f'Activated archive period {build_archive_period_option_label(selected_period)} using {archive_hours} hour(s).'
        )
        ui.notify(
            f'Activated {build_archive_period_option_label(selected_period)} using {archive_hours} hour(s).',
            color='positive',
        )
        calibration_panel_state['selected_period_id'] = state.active_archive_period_id or selected_period.period_id
    finally:
        calibration_panel_state['compute_in_progress'] = False
        render_calibration_panel.refresh()


async def handle_compute_from_archive() -> None:
    """Compute a preview for the selected archive period if one is not already running."""

    if calibration_panel_state.get('compute_in_progress'):
        ui.notify('Calibration compute is already running.', color='warning')
        return

    calibration_panel_state['compute_in_progress'] = True
    calibration_panel_state['last_started_at'] = datetime.now().astimezone().isoformat()
    calibration_panel_state['compute_notice'] = 'Calibration run in progress...'
    render_calibration_panel.refresh()
    try:
        await compute_selected_period_preview(show_success_notice=True)
    finally:
        calibration_panel_state['compute_in_progress'] = False
        render_calibration_panel.refresh()


async def activate_latest_archive_period_for_auto_mode(*, archive_hours: int) -> None:
    """Compute and activate the newest archive-backed thresholds when auto mode is enabled."""

    if calibration_panel_state.get('compute_in_progress'):
        return

    calibration_panel_state['compute_in_progress'] = True
    calibration_panel_state['last_started_at'] = datetime.now().astimezone().isoformat()
    calibration_panel_state['compute_notice'] = 'Automatic archive calibration in progress...'
    render_calibration_panel.refresh()

    try:
        try:
            snapshot, selected_period, archive_hours = await asyncio.to_thread(
                _compute_latest_archive_period_snapshot,
                archive_hours,
            )
        except ValueError as exc:
            calibration_panel_state['compute_notice'] = f'Auto calibration failed: {exc}'
            calibration_panel_state['notice'] = f'Automatic mode is on, but latest archive calibration failed: {exc}'
            ui.notify(f'Auto calibration failed: {exc}', color='negative')
            return
        except Exception as exc:
            calibration_panel_state['compute_notice'] = f'Auto calibration failed unexpectedly: {exc}'
            calibration_panel_state['notice'] = f'Automatic mode is on, but latest archive calibration failed: {exc}'
            ui.notify(f'Auto calibration failed: {exc}', color='negative')
            return

        state = activate_runtime_calibration_snapshot(
            snapshot,
            archive_period_id=selected_period.period_id,
            archive_period_end=isoformat_utc(selected_period.nominal_end_time),
            archive_hours=archive_hours,
            activation_mode='auto',
        )
        calibration_panel_state['preview_snapshot'] = snapshot
        calibration_panel_state['preview_period_id'] = selected_period.period_id
        calibration_panel_state['preview_archive_hours'] = archive_hours
        calibration_panel_state['selected_period_id'] = state.active_archive_period_id or selected_period.period_id
        calibration_panel_state['compute_notice'] = (
            f'Auto-calibrated latest archive period {build_archive_period_option_label(selected_period)} using {archive_hours} hour(s).'
        )
        calibration_panel_state['notice'] = (
            f'Automatic mode is active. Runtime now follows archive period {build_archive_period_option_label(selected_period)} using {archive_hours} hour(s), and will refresh again when the next hour arrives.'
        )
        ui.notify(
            f'Auto-calibrated {build_archive_period_option_label(selected_period)} using {archive_hours} hour(s).',
            color='positive',
        )
    finally:
        calibration_panel_state['compute_in_progress'] = False
        render_calibration_panel.refresh()


class DashboardPushSubscriber:
    """Keep the monitor UI refreshed from Redis Pub/Sub with automatic listener recovery."""

    def __init__(self, channels: list[str], refresh_callback) -> None:
        self.channels = channels
        self.refresh_callback = refresh_callback
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        self.pubsub: redis.client.PubSub | None = None
        self.task: asyncio.Task | None = None
        self.running = False

    def startup(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = background_tasks.create(self.run(), name='monitor_dashboard_listener')

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
        """Reconnect the Redis listener if the subscription loop exits unexpectedly."""

        try:
            while self.running:
                try:
                    await self.listen()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f'⚠️ Monitor dashboard listener error: {exc}')
                    await asyncio.sleep(1.0)
        finally:
            if self.pubsub is not None:
                self.pubsub.close()
                self.pubsub = None

    async def listen(self) -> None:
        self.pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(*self.channels)
        try:
            while self.running:
                message = self.pubsub.get_message(timeout=1.0)
                if message and message.get('type') == 'message':
                    try:
                        self.refresh_callback()
                    except Exception as exc:
                        print(f'⚠️ Monitor dashboard refresh failed: {exc}')
                await asyncio.sleep(0.05)
        finally:
            if self.pubsub is not None:
                self.pubsub.close()
                self.pubsub = None



@ui.refreshable
def render_calibration_panel() -> None:
    view_model = resolve_calibration_view_model()
    periods = view_model['periods']
    active_state = view_model['active_state']
    selected_period = view_model['selected_period']
    selected_period_id = view_model['selected_period_id']
    selected_snapshot = view_model['selected_snapshot']
    selected_snapshot_status = view_model['selected_snapshot_status']
    displayed_period = view_model['displayed_period']
    displayed_archive_hours = view_model['displayed_archive_hours']
    archive_hours = view_model['archive_hours']
    notice = view_model['notice']
    compute_notice = view_model['compute_notice']
    compute_in_progress = view_model['compute_in_progress']
    last_started_at = view_model['last_started_at']

    # ui.label('Calibration History').classes('section-title')
    with ui.element('div').classes('glass-panel gap-4 full-width-panel calibration-panel'):
        with ui.row().classes('items-center justify-between w-full'):
            with ui.column().classes('gap-1'):
                ui.label('Calibration Periods').classes('panel-title')
                ui.label(
                    'Select an archive period, choose trailing archive hours, compute a preview, then activate it for runtime.',
                ).classes('panel-caption')
            if active_state:
                ui.label(
                    f'Mode {active_state.activation_mode.upper()}',
                ).classes(f'status-badge {"signal-hot" if active_state.activation_mode == "auto" else "signal-warm"}')

        with ui.row().classes('w-full items-end gap-3 calibration-controls'):
            if periods:
                ui.select(
                    options={period.period_id: build_archive_period_option_label(period) for period in reversed(periods)},
                    value=selected_period_id,
                    label='Archive Period',
                    on_change=handle_archive_period_selection,
                ).classes('calibration-select')
            ui.select(
                options=ARCHIVE_HOURS_OPTIONS,
                value=archive_hours,
                label='Archive Hours',
                on_change=handle_archive_hours_change,
            ).classes('calibration-select')
            ui.toggle(
                {'auto': 'Auto', 'manual': 'Manual'},
                value=(active_state.activation_mode if active_state else 'auto'),
                on_change=handle_activation_mode_change,
            ).classes('calibration-toggle')
            compute_button = ui.button('Preview Thresholds', on_click=handle_compute_from_archive).classes('btn-secondary')
            if compute_in_progress:
                compute_button.props('loading disable')
                ui.spinner(size='sm').classes('self-center text-amber-5')
                ui.label('Computing...').classes('panel-caption self-center')
            elif compute_notice:
                ui.label('Compute complete').classes('panel-caption self-center text-positive')
            if periods:
                activate_button = ui.button('Activate Selected', on_click=handle_calibration_activation).classes('btn-secondary')
                if selected_snapshot_status == 'active':
                    activate_button.props('disable')

        if notice:
            ui.label(notice).classes('calibration-notice')
        if compute_notice:
            compute_message = compute_notice
            if compute_in_progress and last_started_at:
                compute_message = f'{compute_message} Started at {format_iso_time(last_started_at)}.'
            ui.label(compute_message).classes('calibration-notice')

        if not periods:
            ui.label('No archive periods found yet. Wait for hourly trade archive files to appear.').classes('empty-state')
            return

        if selected_period is None:
            ui.label('Select an archive period to inspect or compute thresholds.').classes('empty-state')
            return

        ui.label(
            f'Selected archive period  {build_archive_period_option_label(selected_period)}  ·  trailing window  {archive_hours} hour(s)'
        ).classes('calibration-period-line')

        if selected_snapshot is None:
            ui.label('Compute thresholds for this archive period and hour window to preview them here.').classes('empty-state')
            return

        if (
            displayed_period is not None
            and selected_period is not None
            and (
                displayed_period.period_id != selected_period.period_id
                or displayed_archive_hours != archive_hours
            )
        ):
            ui.label(
                f'Displaying computed thresholds for {build_archive_period_option_label(displayed_period)}  ·  trailing window  {displayed_archive_hours} hour(s).'
            ).classes('calibration-period-line')

        period_start, period_end = calibration_period_summary(selected_snapshot)
        ui.label(
            f'Sample period  {period_start}  →  {period_end}  ·  {len(selected_snapshot.tickers)} tickers'
        ).classes('calibration-period-line')

        with ui.row().classes('w-full gap-3 calibration-chip-row'):
            if selected_snapshot_status == 'active':
                ui.label('ACTIVE RUNTIME').classes('status-badge signal-hot')
            elif selected_snapshot_status == 'preview':
                ui.label('COMPUTED PREVIEW').classes('status-badge signal-warm')
            if selected_snapshot.tickers:
                ui.label(f'Archive Window {displayed_archive_hours:g}h').classes('status-badge signal-cold')
                ui.label(f'Window {selected_snapshot.tickers[0].window_ms / 1000:.0f}s').classes('status-badge signal-cold')
                ui.label(f'Sampling {selected_snapshot.tickers[0].sampling_interval_ms}ms').classes('status-badge signal-cold')

        with ui.element('div').classes('calibration-ticker-grid w-full'):
            for entry in selected_snapshot.tickers:
                is_fresh = entry.entry_status != 'reused'
                period_start = format_event_time_ms(entry.source.first_event_time_ms)
                period_end = format_event_time_ms(entry.source.last_event_time_ms)
                with ui.element('div').classes('calibration-ticker-card'):
                    with ui.element('div').classes('calibration-ticker-meta'):
                        with ui.row().classes('items-center gap-3'):
                            ui.label(entry.ticker).classes('calibration-ticker-name')
                            ui.label('Fresh' if is_fresh else 'Reused').classes(
                                f'status-badge {"signal-hot" if is_fresh else "signal-warm"}'
                            )
                        ui.label(f'{period_start}  →  {period_end}').classes('calibration-ticker-period')
                        # ui.label(
                        #     f'{entry.sample_count} samples · P{entry.lower_percentile:.0f} / P{entry.upper_percentile:.0f}'
                        # ).classes('calibration-percentile-note')
                    with ui.element('div').classes('calibration-threshold-grid'):
                        thresholds = [
                            ('Samples', 'Minimum', f'{entry.sample_count}'),
                            ('Volume', f'{entry.thresholds.min_volume_threshold:.3f}', f'{entry.thresholds.max_volume_threshold:.3f}'),
                            ('Trades', f'{entry.thresholds.min_trade_count}', f'{entry.thresholds.max_trade_count}'),
                            ('Std Dev', f'{entry.thresholds.min_std_dev:.5f}', f'{entry.thresholds.max_std_dev:.5f}'),
                        ]
                        for th_label, lo, hi in thresholds:
                            with ui.element('div').classes('calibration-threshold-cell'):
                                ui.label(th_label).classes('calibration-threshold-label')
                                ui.label(lo).classes('calibration-threshold-value calibration-threshold-lo')
                                ui.label('↓').classes('calibration-threshold-arrow')
                                ui.label(hi).classes('calibration-threshold-value calibration-threshold-hi')


@ui.refreshable
def render_overview_section(tickers: list[str]) -> None:
    overview_rows = build_overview_rows(tickers)

    ui.label('Per-Ticker Snapshot').classes('section-title')
    if not overview_rows:
        ui.label('Waiting for rolling metrics from activity_monitor…').classes('empty-state')
        return

    with ui.element('div').classes('ticker-grid w-full'):
        for row in overview_rows:
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
                        ui.label(format_metric(row['latest_trade'].get('price'), 2)).classes('mini-value')
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
                        f'Rolling: {rolling.get("timestamp", "—")} · WAP {format_metric(rolling.get("wap"), 5)} · Slope {format_metric(rolling.get("slope"), 5)}',
                    ).classes('ticker-detail')
                    ui.label(
                        f'Latest setup: {setup.get("setup_start_time", "—")} -> {setup.get("setup_end_time", "—")} · Score {format_metric(setup.get("activity_score"))}',
                    ).classes('ticker-detail')
                    ui.label(
                        f'Minute summary: {minute.get("timestamp", "—")} · Trades {format_metric(minute.get("trades"), 0)} · Volume {format_metric(minute.get("volume"), 3)}',
                    ).classes('ticker-detail')


@ui.refreshable
def render_rolling_panel() -> None:
    rolling_rows = load('rolling_metrics_logs')
    if rolling_rows:
        ui.table(
            columns=ROLLING_COLUMNS,
            rows=rolling_table_rows(rolling_rows),
            row_key='time',
        ).classes('data-table w-full')
    else:
        ui.label('Waiting for rolling diagnostics…').classes('empty-state')


@ui.refreshable
def render_setup_panel() -> None:
    setup_rows = load('trap_logs')
    if setup_rows:
        ui.table(
            columns=SETUP_COLUMNS,
            rows=setup_table_rows(setup_rows),
            row_key='setup_end',
        ).classes('data-table w-full')
    else:
        ui.label('Waiting for finalized setup snapshots…').classes('empty-state')


@ui.refreshable
def render_minute_panel() -> None:
    minute_rows = load('minute_logs')
    if minute_rows:
        ui.table(
            columns=MINUTE_COLUMNS,
            rows=minute_table_rows(minute_rows),
            row_key='minute',
        ).classes('data-table w-full')
    else:
        ui.label('Waiting for minute rollover summaries…').classes('empty-state')


def refresh_monitor_dashboard(tickers: list[str], *, include_calibration: bool = False) -> None:
    """Refresh all monitor dashboard sections that depend on live Redis or calibration state."""

    if include_calibration:
        render_calibration_panel.refresh()
    render_overview_section.refresh(tickers)
    render_rolling_panel.refresh()
    render_setup_panel.refresh()
    render_minute_panel.refresh()


monitor_subscriber = DashboardPushSubscriber(
    [MONITOR_DASHBOARD_UPDATES_CHANNEL, MARKET_DATA_UPDATES_CHANNEL],
    refresh_callback=lambda: refresh_monitor_dashboard(load_tickers()),
)

app.on_startup(monitor_subscriber.startup)
app.on_shutdown(monitor_subscriber.shutdown)


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
                    ui.label(
                        'Rolling trade diagnostics, finalized setup snapshots, and minute rollover summaries',
                    ).classes('hero-subtitle')
                ui.label(f'Updated {datetime.now().strftime("%H:%M:%S")}').classes('header-timestamp')

        with ui.column().classes('content-shell w-full gap-6'):
            render_calibration_panel()
            ui.timer(10.0, render_calibration_panel.refresh)

            with ui.column().classes('gap-3'):
                render_overview_section(tickers)

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
                        render_rolling_panel()
                    with ui.tab_panel(tab_setup).classes('w-full'):
                        render_setup_panel()
                    with ui.tab_panel(tab_minute).classes('w-full'):
                        render_minute_panel()

if __name__ in {'__main__', '__mp_main__'}:
    ui.run(title='Ritrade Monitor', dark=True, favicon='📊', port=8081, reload=False)
