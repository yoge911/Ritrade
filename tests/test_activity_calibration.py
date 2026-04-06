import json
from datetime import datetime, timezone

import pytest

from market_data.models import TradeEvent
from monitor.activity_metrics import compute_window_metrics, trim_trades_to_window
from monitor.activity_monitor import TickerConfig, generate_activity_snapshot, load_runtime_configs
from monitor.calibrate_activity import build_thresholds, sample_window_metrics, validate_thresholds
from monitor.calibration_store import CalibrationSnapshot, CalibrationSourceInfo, CalibrationTickerEntry, ThresholdSet, write_calibration_snapshot


def build_trade_event(event_time: int, price: float, quantity: float) -> TradeEvent:
    return TradeEvent(
        symbol='btcusdc',
        event_time=event_time,
        price=price,
        quantity=quantity,
        is_buyer_maker=False,
    )


def build_config() -> TickerConfig:
    return TickerConfig(
        ticker='BTCUSDC',
        min_volume_threshold=0.1,
        max_volume_threshold=5.0,
        min_trade_count=1,
        max_trade_count=10,
        min_std_dev=0.01,
        max_std_dev=10.0,
    )


def test_shared_window_metrics_match_runtime_snapshot_values():
    trades = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.0, 0.20),
        build_trade_event(3000, 100.3, 0.20),
    ]

    metrics = compute_window_metrics(3000, trades)
    snapshot = generate_activity_snapshot(3000, trades, 'btcusdc', build_config())

    assert snapshot.trades == metrics.trade_count
    assert snapshot.volume == round(metrics.total_volume, 3)
    assert snapshot.std_dev == round(metrics.std_dev, 5)
    assert snapshot.wap == round(metrics.wap, 5)
    assert snapshot.slope == round(metrics.slope, 5)


def test_sampling_uses_same_rolling_window_membership_as_runtime_logic():
    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(5000, 101.0, 0.20),
        build_trade_event(16000, 102.0, 0.20),
        build_trade_event(16500, 103.0, 0.20),
    ]

    samples = sample_window_metrics(
        events,
        start_ms=1000,
        end_ms=17000,
        window_ms=10000,
        sampling_interval_ms=1000,
    )

    sample_16000 = next(sample for sample in samples if sample.event_time_ms == 16000)
    runtime_window = trim_trades_to_window(events, 16000)

    assert [trade.event_time for trade in runtime_window] == [16000]
    assert sample_16000.trade_count == 1
    assert sample_16000.total_volume == 0.2


def test_percentile_thresholds_are_computed_from_sample_metrics():
    samples = [
        compute_window_metrics(1000, [build_trade_event(1000, 100.0, 0.10)]),
        compute_window_metrics(2000, [build_trade_event(2000, 100.0, 0.20), build_trade_event(2001, 100.1, 0.20)]),
        compute_window_metrics(3000, [build_trade_event(3000, 100.0, 0.30), build_trade_event(3001, 100.2, 0.30)]),
        compute_window_metrics(4000, [build_trade_event(4000, 100.0, 0.40), build_trade_event(4001, 100.3, 0.40)]),
        compute_window_metrics(5000, [build_trade_event(5000, 100.0, 0.50), build_trade_event(5001, 100.4, 0.50)]),
    ]

    thresholds = build_thresholds(samples, lower_percentile=0.2, upper_percentile=0.8)

    assert thresholds.min_volume_threshold == pytest.approx(0.34)
    assert thresholds.max_volume_threshold == pytest.approx(0.84)
    assert thresholds.min_trade_count == 1
    assert thresholds.max_trade_count == 2
    assert thresholds.min_std_dev >= 0
    assert thresholds.max_std_dev > thresholds.min_std_dev


def test_invalid_threshold_output_is_rejected():
    thresholds = ThresholdSet(
        min_volume_threshold=1.0,
        max_volume_threshold=1.0,
        min_trade_count=5,
        max_trade_count=5,
        min_std_dev=0.1,
        max_std_dev=0.1,
    )

    with pytest.raises(ValueError):
        validate_thresholds(thresholds, sample_count=10, min_sample_count=100)


def test_runtime_config_loader_reads_calibration_json(tmp_path):
    calibration_path = tmp_path / 'activity_thresholds.json'
    snapshot = CalibrationSnapshot(
        metric_version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        tickers=[
            CalibrationTickerEntry(
                ticker='BTCUSDC',
                window_ms=10000,
                sampling_interval_ms=1000,
                recalculated_at=datetime.now(timezone.utc).isoformat(),
                lookback_duration_minutes=120,
                sample_count=500,
                lower_percentile=0.2,
                upper_percentile=0.8,
                source=CalibrationSourceInfo(
                    type='jsonl_trade_archive',
                    files=2,
                    first_event_time_ms=1,
                    last_event_time_ms=2,
                ),
                thresholds=ThresholdSet(
                    min_volume_threshold=0.1,
                    max_volume_threshold=1.2,
                    min_trade_count=2,
                    max_trade_count=20,
                    min_std_dev=0.01,
                    max_std_dev=0.5,
                ),
            )
        ],
    )
    write_calibration_snapshot(snapshot, calibration_path)

    configs = load_runtime_configs(calibration_path=calibration_path)

    assert len(configs) == 1
    assert configs[0].ticker == 'BTCUSDC'
    assert configs[0].max_trade_count == 20
