"""Build calibration runs from archived trade files and record them into run history."""

from __future__ import annotations

import argparse
import math
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from market_data.models import TradeEvent
from monitor.activity_metrics import (
    ACTIVITY_METRIC_VERSION,
    ROLLING_WINDOW_MS,
    WindowMetrics,
    compute_window_metrics,
)
from monitor.activity_monitor import load_enabled_tickers
from monitor.calibration_store import (
    ActiveCalibrationState,
    DEFAULT_CALIBRATION_PATH,
    CalibrationSnapshot,
    CalibrationSourceInfo,
    CalibrationTickerEntry,
    ThresholdSet,
    activate_runtime_calibration_snapshot,
    isoformat_utc,
    load_active_calibration_state,
    load_calibration_run,
    load_calibration_snapshot,
    write_calibration_run,
    record_calibration_run,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = ROOT_DIR / 'data' / 'trade_archive'
DEFAULT_LOOKBACK_MINUTES = 120
DEFAULT_RECOMPUTE_MINUTES = 30
DEFAULT_SAMPLING_INTERVAL_MS = 1000
DEFAULT_LOWER_PERCENTILE = 0.2
DEFAULT_UPPER_PERCENTILE = 0.8
DEFAULT_MIN_SAMPLE_COUNT = 100
DEFAULT_HISTORY_RETENTION_DAYS = 5


@dataclass(frozen=True)
class ArchivePeriod:
    """One hourly archive-file period surfaced in the monitor UI selector."""

    period_id: str
    nominal_end_time: datetime
    effective_end_time: datetime


def utc_now() -> datetime:
    """Return the current UTC timestamp used for calibration run generation."""

    return datetime.now(timezone.utc)


def generate_run_id(now: datetime) -> str:
    """Generate a stable human-readable run id from a UTC timestamp."""

    return now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def archive_hour_end_times(archive_root: Path, tickers: list[str]) -> list[datetime]:
    """Return unique hourly archive end-times across the requested tickers."""

    now = utc_now()
    end_times: set[datetime] = set()
    for ticker in tickers:
        ticker_root = archive_root / ticker.lower()
        if not ticker_root.exists():
            continue
        for path in ticker_root.rglob('*.jsonl'):
            try:
                hour_start = datetime(
                    int(path.parts[-4]),
                    int(path.parts[-3]),
                    int(path.parts[-2]),
                    int(path.stem),
                    tzinfo=timezone.utc,
                )
            except (IndexError, ValueError):
                continue
            end_times.add(min(hour_start + timedelta(hours=1) - timedelta(seconds=1), now))
    return sorted(end_times)


def archive_periods(archive_root: Path, tickers: list[str]) -> list[ArchivePeriod]:
    """Return one stable archive-file-backed period per hourly file across the requested tickers."""

    now = utc_now()
    periods: dict[str, ArchivePeriod] = {}
    for ticker in tickers:
        ticker_root = archive_root / ticker.lower()
        if not ticker_root.exists():
            continue
        for path in ticker_root.rglob('*.jsonl'):
            try:
                hour_start = datetime(
                    int(path.parts[-4]),
                    int(path.parts[-3]),
                    int(path.parts[-2]),
                    int(path.stem),
                    tzinfo=timezone.utc,
                )
            except (IndexError, ValueError):
                continue
            nominal_end_time = hour_start + timedelta(hours=1) - timedelta(seconds=1)
            period_id = generate_run_id(nominal_end_time)
            periods[period_id] = ArchivePeriod(
                period_id=period_id,
                nominal_end_time=nominal_end_time,
                effective_end_time=min(nominal_end_time, now),
            )
    return sorted(periods.values(), key=lambda period: period.nominal_end_time)


def latest_archive_period(archive_root: Path, tickers: list[str]) -> ArchivePeriod | None:
    """Return the newest available archive-backed period across the configured tickers."""

    periods = archive_periods(archive_root, tickers)
    return periods[-1] if periods else None


def archive_window_bounds(end_time: datetime, archive_hours: int) -> tuple[datetime, datetime]:
    """Return hour-aligned bounds covering exactly the requested trailing archive files."""

    end_utc = end_time.astimezone(timezone.utc)
    end_hour_start = end_utc.replace(minute=0, second=0, microsecond=0)
    start_hour = end_hour_start - timedelta(hours=max(archive_hours - 1, 0))
    return start_hour, end_utc


def hourly_archive_paths(archive_root: Path, ticker: str, start_time: datetime, end_time: datetime) -> list[Path]:
    """Enumerate the hourly archive files needed to cover a calibration lookback window."""

    paths: list[Path] = []
    current = start_time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end_hour = end_time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    while current <= end_hour:
        paths.append(
            archive_root
            / ticker.lower()
            / current.strftime('%Y')
            / current.strftime('%m')
            / current.strftime('%d')
            / f'{current.strftime("%H")}.jsonl'
        )
        current += timedelta(hours=1)
    return paths


def load_trade_events(
    archive_root: Path,
    ticker: str,
    start_time: datetime,
    end_time: datetime,
) -> tuple[list[TradeEvent], int]:
    """Load and time-filter archived trade events for one ticker from its hourly files."""

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    paths = hourly_archive_paths(archive_root, ticker, start_time, end_time)
    events: list[TradeEvent] = []
    used_files = 0

    for path in paths:
        if not path.exists():
            continue
        used_files += 1
        with path.open('r') as archive_file:
            for line in archive_file:
                line = line.strip()
                if not line:
                    continue
                event = TradeEvent.model_validate_json(line)
                if start_ms <= event.event_time <= end_ms:
                    events.append(event)

    events.sort(key=lambda event: event.event_time)
    return events, used_files


def load_trade_events_for_archive_hours(
    archive_root: Path,
    ticker: str,
    *,
    archive_hours: int,
    end_time: datetime,
) -> tuple[list[TradeEvent], int, datetime]:
    """Load archived trades from the exact trailing archive-hour slice ending at `end_time`."""

    start_time, bounded_end_time = archive_window_bounds(end_time, archive_hours)
    events, used_files = load_trade_events(
        archive_root,
        ticker,
        start_time,
        bounded_end_time,
    )
    return events, used_files, start_time


def align_to_interval(ms: int, interval_ms: int) -> int:
    """Round a timestamp up to the next sampling interval boundary."""

    return int(math.ceil(ms / interval_ms) * interval_ms)


def sample_window_metrics(
    events: list[TradeEvent],
    *,
    start_ms: int,
    end_ms: int,
    window_ms: int,
    sampling_interval_ms: int,
) -> list[WindowMetrics]:
    """Replay trades into rolling-window metric samples across the calibration period."""

    if not events:
        return []

    next_sample_time_ms = align_to_interval(max(start_ms, events[0].event_time), sampling_interval_ms)
    rolling_events: deque[TradeEvent] = deque()
    samples: list[WindowMetrics] = []

    for event in events:
        rolling_events.append(event)
        while next_sample_time_ms <= min(event.event_time, end_ms):
            sample_trades = [
                trade
                for trade in rolling_events
                if next_sample_time_ms - window_ms <= trade.event_time <= next_sample_time_ms
            ]
            if sample_trades:
                samples.append(compute_window_metrics(next_sample_time_ms, sample_trades))

            sample_cutoff = next_sample_time_ms - window_ms
            while rolling_events and rolling_events[0].event_time < sample_cutoff:
                rolling_events.popleft()

            next_sample_time_ms += sampling_interval_ms

    return samples


def build_thresholds(
    samples: list[WindowMetrics],
    *,
    lower_percentile: float,
    upper_percentile: float,
) -> ThresholdSet:
    """Compute percentile-based thresholds from sampled rolling-window metrics."""

    volumes = [sample.total_volume for sample in samples]
    trade_counts = [sample.trade_count for sample in samples]
    std_devs = [sample.std_dev for sample in samples]

    return ThresholdSet(
        min_volume_threshold=float(np.quantile(volumes, lower_percentile)),
        max_volume_threshold=float(np.quantile(volumes, upper_percentile)),
        min_trade_count=int(math.floor(float(np.quantile(trade_counts, lower_percentile)))),
        max_trade_count=int(math.floor(float(np.quantile(trade_counts, upper_percentile)))),
        min_std_dev=float(np.quantile(std_devs, lower_percentile)),
        max_std_dev=float(np.quantile(std_devs, upper_percentile)),
    )


def validate_thresholds(thresholds: ThresholdSet, *, sample_count: int, min_sample_count: int) -> None:
    """Reject unusable threshold sets before they are written into calibration history."""

    if sample_count < min_sample_count:
        raise ValueError(f'Not enough samples: {sample_count} < {min_sample_count}')

    values = thresholds.model_dump()
    if any(not np.isfinite(value) for value in values.values()):
        raise ValueError('Threshold set contains NaN or infinite values')

    if any(value < 0 for value in values.values()):
        raise ValueError('Threshold set contains negative values')

    if thresholds.min_volume_threshold >= thresholds.max_volume_threshold:
        raise ValueError('Volume thresholds are not strictly increasing')
    if thresholds.min_trade_count >= thresholds.max_trade_count:
        raise ValueError('Trade-count thresholds are not strictly increasing')
    if thresholds.min_std_dev >= thresholds.max_std_dev:
        raise ValueError('Std-dev thresholds are not strictly increasing')


def calibrate_ticker(
    ticker: str,
    *,
    archive_root: Path,
    lookback_minutes: int,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
    end_time: datetime,
) -> CalibrationTickerEntry:
    """Create a fresh calibration entry for a single ticker from archived trade samples."""

    start_time = end_time - timedelta(minutes=lookback_minutes)
    events, used_files = load_trade_events(archive_root, ticker, start_time, end_time)
    samples = sample_window_metrics(
        events,
        start_ms=int(start_time.timestamp() * 1000),
        end_ms=int(end_time.timestamp() * 1000),
        window_ms=window_ms,
        sampling_interval_ms=sampling_interval_ms,
    )
    thresholds = build_thresholds(
        samples,
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
    )
    validate_thresholds(thresholds, sample_count=len(samples), min_sample_count=min_sample_count)

    return CalibrationTickerEntry(
        ticker=ticker.upper(),
        window_ms=window_ms,
        sampling_interval_ms=sampling_interval_ms,
        recalculated_at=isoformat_utc(end_time),
        lookback_duration_minutes=lookback_minutes,
        sample_count=len(samples),
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
        source=CalibrationSourceInfo(
            type='jsonl_trade_archive',
            files=used_files,
            first_event_time_ms=events[0].event_time if events else None,
            last_event_time_ms=events[-1].event_time if events else None,
        ),
        thresholds=thresholds,
        entry_status='fresh',
        source_run_id=None,
    )


def calibrate_ticker_for_archive_hours(
    ticker: str,
    *,
    archive_root: Path,
    archive_hours: int,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
    end_time: datetime,
) -> CalibrationTickerEntry:
    """Create a calibration entry using exactly the requested trailing archive-hour files."""

    events, used_files, start_time = load_trade_events_for_archive_hours(
        archive_root,
        ticker,
        archive_hours=archive_hours,
        end_time=end_time,
    )
    bounded_end_time = end_time.astimezone(timezone.utc)
    samples = sample_window_metrics(
        events,
        start_ms=int(start_time.timestamp() * 1000),
        end_ms=int(bounded_end_time.timestamp() * 1000),
        window_ms=window_ms,
        sampling_interval_ms=sampling_interval_ms,
    )
    thresholds = build_thresholds(
        samples,
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
    )
    validate_thresholds(thresholds, sample_count=len(samples), min_sample_count=min_sample_count)

    return CalibrationTickerEntry(
        ticker=ticker.upper(),
        window_ms=window_ms,
        sampling_interval_ms=sampling_interval_ms,
        recalculated_at=isoformat_utc(bounded_end_time),
        lookback_duration_minutes=archive_hours * 60,
        sample_count=len(samples),
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
        source=CalibrationSourceInfo(
            type='jsonl_trade_archive',
            files=used_files,
            first_event_time_ms=events[0].event_time if events else None,
            last_event_time_ms=events[-1].event_time if events else None,
        ),
        thresholds=thresholds,
        entry_status='fresh',
        source_run_id=None,
    )


def compute_archive_period_snapshot_for_hours(
    tickers: list[str],
    *,
    archive_root: Path,
    output_path: Path,
    archive_hours: int,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
    archive_period: ArchivePeriod,
    previous_snapshot: CalibrationSnapshot | None = None,
) -> CalibrationSnapshot:
    """Compute one archive-period snapshot using the selected trailing hour window."""

    now = archive_period.effective_end_time.astimezone(timezone.utc)
    previous_snapshot = previous_snapshot if previous_snapshot is not None else load_calibration_snapshot(output_path)
    previous_entries = {
        entry.ticker.lower(): (entry, previous_snapshot.run_id)
        for entry in (previous_snapshot.tickers if previous_snapshot else [])
    }

    entries: list[CalibrationTickerEntry] = []
    fresh_entry_count = 0
    reused_entry_count = 0
    for ticker in tickers:
        try:
            entry = calibrate_ticker_for_archive_hours(
                ticker,
                archive_root=archive_root,
                archive_hours=archive_hours,
                sampling_interval_ms=sampling_interval_ms,
                lower_percentile=lower_percentile,
                upper_percentile=upper_percentile,
                window_ms=window_ms,
                min_sample_count=min_sample_count,
                end_time=now,
            )
            print(f'✅ Calibrated {ticker.upper()} with {entry.sample_count} samples from {archive_hours} archive hour(s).')
            fresh_entry_count += 1
        except ValueError as exc:
            previous_entry = previous_entries.get(ticker.lower())
            if previous_entry is None:
                print(f'⚠️ Skipping {ticker.upper()}: {exc}')
                continue
            entry, source_run_id = previous_entry
            entry = entry.model_copy(update={
                'entry_status': 'reused',
                'source_run_id': source_run_id,
                'recalculated_at': isoformat_utc(now),
            })
            print(f'⚠️ Keeping previous calibration for {ticker.upper()}: {exc}')
            reused_entry_count += 1
        entries.append(entry)

    return CalibrationSnapshot(
        run_id=archive_period.period_id,
        metric_version=ACTIVITY_METRIC_VERSION,
        generated_at=isoformat_utc(now),
        fresh_entry_count=fresh_entry_count,
        reused_entry_count=reused_entry_count,
        tickers=entries,
    )


def compute_latest_archive_period_snapshot_for_hours(
    tickers: list[str],
    *,
    archive_root: Path,
    output_path: Path,
    archive_hours: int,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
    previous_snapshot: CalibrationSnapshot | None = None,
) -> tuple[CalibrationSnapshot, ArchivePeriod]:
    """Compute thresholds for the newest available archive period using the requested trailing hour window."""

    archive_period = latest_archive_period(archive_root, tickers)
    if archive_period is None:
        raise ValueError('No archive periods found yet.')

    snapshot = compute_archive_period_snapshot_for_hours(
        tickers,
        archive_root=archive_root,
        output_path=output_path,
        archive_hours=archive_hours,
        sampling_interval_ms=sampling_interval_ms,
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
        window_ms=window_ms,
        min_sample_count=min_sample_count,
        archive_period=archive_period,
        previous_snapshot=previous_snapshot,
    )
    if not snapshot.tickers:
        raise ValueError('No thresholds could be computed for the latest archive period.')
    return snapshot, archive_period


def run_auto_archive_calibration(
    tickers: list[str],
    *,
    archive_root: Path,
    output_path: Path,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
) -> tuple[CalibrationSnapshot, ArchivePeriod, ActiveCalibrationState] | None:
    """If auto mode is enabled, compute and activate thresholds from the newest archive period once per new hour."""

    active_state = load_active_calibration_state()
    if active_state is None or active_state.activation_mode != 'auto':
        return None

    archive_hours = max(int(active_state.auto_archive_hours), 1)
    archive_period = latest_archive_period(archive_root, tickers)
    if archive_period is None:
        return None

    if (
        active_state.active_archive_period_id == archive_period.period_id
        and active_state.active_archive_hours == archive_hours
    ):
        return None

    snapshot = compute_archive_period_snapshot_for_hours(
        tickers,
        archive_root=archive_root,
        output_path=output_path,
        archive_hours=archive_hours,
        sampling_interval_ms=sampling_interval_ms,
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
        window_ms=window_ms,
        min_sample_count=min_sample_count,
        archive_period=archive_period,
    )
    if not snapshot.tickers:
        return None

    updated_state = activate_runtime_calibration_snapshot(
        snapshot,
        archive_period_id=archive_period.period_id,
        archive_period_end=isoformat_utc(archive_period.nominal_end_time),
        archive_hours=archive_hours,
        activation_mode='auto',
    )
    return snapshot, archive_period, updated_state


def run_calibration(
    tickers: list[str],
    *,
    archive_root: Path,
    output_path: Path,
    lookback_minutes: int,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
    end_time: datetime | None = None,
    previous_snapshot: CalibrationSnapshot | None = None,
) -> CalibrationSnapshot:
    """Build one immutable calibration run, reusing prior ticker entries when recalculation fails."""

    now = end_time.astimezone(timezone.utc) if end_time is not None else utc_now()
    run_id = generate_run_id(now)
    previous_snapshot = previous_snapshot if previous_snapshot is not None else load_calibration_snapshot(output_path)
    previous_entries = {
        entry.ticker.lower(): (entry, previous_snapshot.run_id)
        for entry in (previous_snapshot.tickers if previous_snapshot else [])
    }

    entries: list[CalibrationTickerEntry] = []
    fresh_entry_count = 0
    reused_entry_count = 0
    for ticker in tickers:
        try:
            entry = calibrate_ticker(
                ticker,
                archive_root=archive_root,
                lookback_minutes=lookback_minutes,
                sampling_interval_ms=sampling_interval_ms,
                lower_percentile=lower_percentile,
                upper_percentile=upper_percentile,
                window_ms=window_ms,
                min_sample_count=min_sample_count,
                end_time=now,
            )
            print(f'✅ Calibrated {ticker.upper()} with {entry.sample_count} samples.')
            fresh_entry_count += 1
        except ValueError as exc:
            previous_entry = previous_entries.get(ticker.lower())
            if previous_entry is None:
                print(f'⚠️ Skipping {ticker.upper()}: {exc}')
                continue
            entry, source_run_id = previous_entry
            entry = entry.model_copy(update={
                'entry_status': 'reused',
                'source_run_id': source_run_id,
                'recalculated_at': isoformat_utc(now),
            })
            print(f'⚠️ Keeping previous calibration for {ticker.upper()}: {exc}')
            reused_entry_count += 1
        entries.append(entry)

    return CalibrationSnapshot(
        run_id=run_id,
        metric_version=ACTIVITY_METRIC_VERSION,
        generated_at=isoformat_utc(now),
        fresh_entry_count=fresh_entry_count,
        reused_entry_count=reused_entry_count,
        tickers=entries,
    )


def backfill_archive_calibration_runs(
    tickers: list[str],
    *,
    archive_root: Path,
    output_path: Path,
    lookback_minutes: int,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
    retention_days: int,
) -> tuple[list[CalibrationSnapshot], ActiveCalibrationState | None, int]:
    """Create any missing historical calibration runs represented by archive hours."""

    end_times = archive_hour_end_times(archive_root, tickers)
    if not end_times:
        return [], None, 0

    created_snapshots: list[CalibrationSnapshot] = []
    skipped_existing = 0
    latest_state: ActiveCalibrationState | None = None
    latest_index = len(end_times) - 1
    previous_snapshot: CalibrationSnapshot | None = None

    for index, end_time in enumerate(end_times):
        run_id = generate_run_id(end_time)
        existing_snapshot = load_calibration_run(run_id)
        if existing_snapshot is not None:
            previous_snapshot = existing_snapshot
            skipped_existing += 1
            continue

        snapshot = run_calibration(
            tickers,
            archive_root=archive_root,
            output_path=output_path,
            lookback_minutes=lookback_minutes,
            sampling_interval_ms=sampling_interval_ms,
            lower_percentile=lower_percentile,
            upper_percentile=upper_percentile,
            window_ms=window_ms,
            min_sample_count=min_sample_count,
            end_time=end_time,
            previous_snapshot=previous_snapshot,
        )
        if not snapshot.tickers:
            continue

        if index == latest_index:
            _, latest_state = record_calibration_run(
                snapshot,
                retention_days=retention_days,
            )
        else:
            write_calibration_run(snapshot)
        created_snapshots.append(snapshot)
        previous_snapshot = snapshot

    return created_snapshots, latest_state, skipped_existing


def backfill_archive_calibration_runs_for_hours(
    tickers: list[str],
    *,
    archive_root: Path,
    output_path: Path,
    archive_hours: int,
    sampling_interval_ms: int,
    lower_percentile: float,
    upper_percentile: float,
    window_ms: int,
    min_sample_count: int,
    retention_days: int,
) -> tuple[list[CalibrationSnapshot], ActiveCalibrationState | None, int]:
    """Create any missing historical calibration runs using an explicit trailing archive-hour window."""

    end_times = archive_hour_end_times(archive_root, tickers)
    if not end_times:
        return [], None, 0

    created_snapshots: list[CalibrationSnapshot] = []
    skipped_existing = 0
    latest_state: ActiveCalibrationState | None = None
    latest_index = len(end_times) - 1
    previous_snapshot: CalibrationSnapshot | None = None

    for index, end_time in enumerate(end_times):
        run_id = generate_run_id(end_time)
        existing_snapshot = load_calibration_run(run_id)
        if existing_snapshot is not None:
            previous_snapshot = existing_snapshot
            skipped_existing += 1
            continue

        now = end_time.astimezone(timezone.utc)
        entries: list[CalibrationTickerEntry] = []
        fresh_entry_count = 0
        reused_entry_count = 0
        previous_entries = {
            entry.ticker.lower(): (entry, previous_snapshot.run_id)
            for entry in (previous_snapshot.tickers if previous_snapshot else [])
        }

        for ticker in tickers:
            try:
                entry = calibrate_ticker_for_archive_hours(
                    ticker,
                    archive_root=archive_root,
                    archive_hours=archive_hours,
                    sampling_interval_ms=sampling_interval_ms,
                    lower_percentile=lower_percentile,
                    upper_percentile=upper_percentile,
                    window_ms=window_ms,
                    min_sample_count=min_sample_count,
                    end_time=now,
                )
                print(f'✅ Calibrated {ticker.upper()} with {entry.sample_count} samples from {archive_hours} archive hour(s).')
                fresh_entry_count += 1
            except ValueError as exc:
                previous_entry = previous_entries.get(ticker.lower())
                if previous_entry is None:
                    print(f'⚠️ Skipping {ticker.upper()}: {exc}')
                    continue
                entry, source_run_id = previous_entry
                entry = entry.model_copy(update={
                    'entry_status': 'reused',
                    'source_run_id': source_run_id,
                    'recalculated_at': isoformat_utc(now),
                })
                print(f'⚠️ Keeping previous calibration for {ticker.upper()}: {exc}')
                reused_entry_count += 1
            entries.append(entry)

        if not entries:
            continue

        snapshot = CalibrationSnapshot(
            run_id=run_id,
            metric_version=ACTIVITY_METRIC_VERSION,
            generated_at=isoformat_utc(now),
            fresh_entry_count=fresh_entry_count,
            reused_entry_count=reused_entry_count,
            tickers=entries,
        )

        if index == latest_index:
            _, latest_state = record_calibration_run(
                snapshot,
                retention_days=retention_days,
            )
        else:
            write_calibration_run(snapshot)
        created_snapshots.append(snapshot)
        previous_snapshot = snapshot

    return created_snapshots, latest_state, skipped_existing


def parse_args() -> argparse.Namespace:
    """Parse CLI options for the long-running calibration job."""

    parser = argparse.ArgumentParser(description='Compute rolling-window activity thresholds from archived trade events.')
    parser.add_argument('--tickers', nargs='*', help='Optional ticker override list')
    parser.add_argument('--archive-root', default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument('--output', default=str(DEFAULT_CALIBRATION_PATH))
    parser.add_argument('--lookback-minutes', type=int, default=DEFAULT_LOOKBACK_MINUTES)
    parser.add_argument('--recompute-minutes', type=int, default=DEFAULT_RECOMPUTE_MINUTES)
    parser.add_argument('--sampling-interval-ms', type=int, default=DEFAULT_SAMPLING_INTERVAL_MS)
    parser.add_argument('--lower-percentile', type=float, default=DEFAULT_LOWER_PERCENTILE)
    parser.add_argument('--upper-percentile', type=float, default=DEFAULT_UPPER_PERCENTILE)
    parser.add_argument('--window-ms', type=int, default=ROLLING_WINDOW_MS)
    parser.add_argument('--min-sample-count', type=int, default=DEFAULT_MIN_SAMPLE_COUNT)
    parser.add_argument('--history-retention-days', type=int, default=DEFAULT_HISTORY_RETENTION_DAYS)
    parser.add_argument('--once', action='store_true')
    return parser.parse_args()


def main() -> None:
    """Continuously recompute calibration runs and record them into history."""

    args = parse_args()
    tickers = [ticker.lower() for ticker in (args.tickers or load_enabled_tickers())]
    archive_root = Path(args.archive_root)
    output_path = Path(args.output)

    if not tickers:
        print('❌ No tickers configured for calibration.')
        return

    while True:
        snapshot = run_calibration(
            tickers,
            archive_root=archive_root,
            output_path=output_path,
            lookback_minutes=args.lookback_minutes,
            sampling_interval_ms=args.sampling_interval_ms,
            lower_percentile=args.lower_percentile,
            upper_percentile=args.upper_percentile,
            window_ms=args.window_ms,
            min_sample_count=args.min_sample_count,
        )
        history_path, active_state = record_calibration_run(
            snapshot,
            retention_days=args.history_retention_days,
        )
        print(
            '📂 Wrote calibration snapshot '
            f'{snapshot.run_id} to {history_path} '
            f'(latest={active_state.latest_run_id}, active={active_state.active_run_id}, mode={active_state.activation_mode})',
        )

        auto_result = run_auto_archive_calibration(
            tickers,
            archive_root=archive_root,
            output_path=output_path,
            sampling_interval_ms=args.sampling_interval_ms,
            lower_percentile=args.lower_percentile,
            upper_percentile=args.upper_percentile,
            window_ms=args.window_ms,
            min_sample_count=args.min_sample_count,
        )
        if auto_result is not None:
            _, archive_period, active_state = auto_result
            print(
                '⚡ Activated latest archive-backed auto calibration '
                f'{archive_period.period_id} '
                f'({active_state.auto_archive_hours} hour(s), mode={active_state.activation_mode})',
            )

        if args.once:
            return
        time.sleep(args.recompute_minutes * 60)


if __name__ == '__main__':
    main()
