from __future__ import annotations

import argparse
import math
import time
from collections import deque
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
    DEFAULT_CALIBRATION_PATH,
    CalibrationSnapshot,
    CalibrationSourceInfo,
    CalibrationTickerEntry,
    ThresholdSet,
    load_calibration_snapshot,
    write_calibration_snapshot,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = ROOT_DIR / 'data' / 'trade_archive'
DEFAULT_LOOKBACK_MINUTES = 120
DEFAULT_RECOMPUTE_MINUTES = 30
DEFAULT_SAMPLING_INTERVAL_MS = 1000
DEFAULT_LOWER_PERCENTILE = 0.2
DEFAULT_UPPER_PERCENTILE = 0.8
DEFAULT_MIN_SAMPLE_COUNT = 100


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def hourly_archive_paths(archive_root: Path, ticker: str, start_time: datetime, end_time: datetime) -> list[Path]:
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


def align_to_interval(ms: int, interval_ms: int) -> int:
    return int(math.ceil(ms / interval_ms) * interval_ms)


def sample_window_metrics(
    events: list[TradeEvent],
    *,
    start_ms: int,
    end_ms: int,
    window_ms: int,
    sampling_interval_ms: int,
) -> list[WindowMetrics]:
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
    )


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
) -> CalibrationSnapshot:
    now = utc_now()
    previous_snapshot = load_calibration_snapshot(output_path)
    previous_entries = {
        entry.ticker.lower(): entry
        for entry in (previous_snapshot.tickers if previous_snapshot else [])
    }

    entries: list[CalibrationTickerEntry] = []
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
        except ValueError as exc:
            entry = previous_entries.get(ticker.lower())
            if entry is None:
                print(f'⚠️ Skipping {ticker.upper()}: {exc}')
                continue
            print(f'⚠️ Keeping previous calibration for {ticker.upper()}: {exc}')
        entries.append(entry)

    return CalibrationSnapshot(
        metric_version=ACTIVITY_METRIC_VERSION,
        generated_at=isoformat_utc(now),
        tickers=entries,
    )


def parse_args() -> argparse.Namespace:
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
    parser.add_argument('--once', action='store_true')
    return parser.parse_args()


def main() -> None:
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
        path = write_calibration_snapshot(snapshot, output_path)
        print(f'📂 Wrote calibration snapshot to {path}')

        if args.once:
            return
        time.sleep(args.recompute_minutes * 60)


if __name__ == '__main__':
    main()
