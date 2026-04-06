"""Coverage for calibration history, activation semantics, and calibration UI view helpers."""

from datetime import datetime, timedelta, timezone

import pytest

import monitor.activity_monitor as activity_monitor_module
import monitor.calibrate_activity as calibrate_activity_module
import monitor.calibration_store as calibration_store_module
from market_data.models import TradeEvent
from monitor import app as monitor_app
from monitor.activity_metrics import compute_window_metrics, trim_trades_to_window
from monitor.activity_monitor import TickerConfig, generate_activity_snapshot, load_runtime_configs
from monitor.calibrate_activity import build_thresholds, run_calibration, sample_window_metrics, validate_thresholds
from monitor.calibration_store import (
    ActiveCalibrationState,
    CalibrationSnapshot,
    CalibrationSourceInfo,
    CalibrationTickerEntry,
    ThresholdSet,
    activate_calibration_run,
    list_calibration_runs,
    load_active_calibration_state,
    load_calibration_run,
    load_calibration_snapshot,
    record_calibration_run,
    resolve_active_calibration_snapshot,
    set_activation_mode,
    write_calibration_snapshot,
)


def build_trade_event(event_time: int, price: float, quantity: float) -> TradeEvent:
    """Create a compact trade event fixture for calibration and runtime metric tests."""

    return TradeEvent(
        symbol='btcusdc',
        event_time=event_time,
        price=price,
        quantity=quantity,
        is_buyer_maker=False,
    )


def build_config() -> TickerConfig:
    """Return a permissive ticker config used by shared metric tests."""

    return TickerConfig(
        ticker='BTCUSDC',
        min_volume_threshold=0.1,
        max_volume_threshold=5.0,
        min_trade_count=1,
        max_trade_count=10,
        min_std_dev=0.01,
        max_std_dev=10.0,
    )


def build_ticker_entry(
    ticker: str,
    *,
    entry_status: str = 'fresh',
    source_run_id: str | None = None,
    sample_count: int = 500,
) -> CalibrationTickerEntry:
    """Create a calibration entry fixture with optional freshness provenance."""

    return CalibrationTickerEntry(
        ticker=ticker,
        window_ms=10000,
        sampling_interval_ms=1000,
        recalculated_at=datetime.now(timezone.utc).isoformat(),
        lookback_duration_minutes=120,
        sample_count=sample_count,
        lower_percentile=0.2,
        upper_percentile=0.8,
        source=CalibrationSourceInfo(
            type='jsonl_trade_archive',
            files=2,
            first_event_time_ms=1_700_000_000_000,
            last_event_time_ms=1_700_000_060_000,
        ),
        thresholds=ThresholdSet(
            min_volume_threshold=0.1,
            max_volume_threshold=1.2,
            min_trade_count=2,
            max_trade_count=20,
            min_std_dev=0.01,
            max_std_dev=0.5,
        ),
        entry_status=entry_status,
        source_run_id=source_run_id,
    )


def build_snapshot(
    run_id: str,
    *,
    generated_at: str | None = None,
    tickers: list[CalibrationTickerEntry] | None = None,
    fresh_entry_count: int | None = None,
    reused_entry_count: int | None = None,
) -> CalibrationSnapshot:
    """Build an immutable calibration run fixture for storage and UI tests."""

    ticker_entries = tickers or [build_ticker_entry('BTCUSDC')]
    return CalibrationSnapshot(
        run_id=run_id,
        metric_version=1,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
        fresh_entry_count=fresh_entry_count if fresh_entry_count is not None else sum(entry.entry_status == 'fresh' for entry in ticker_entries),
        reused_entry_count=reused_entry_count if reused_entry_count is not None else sum(entry.entry_status == 'reused' for entry in ticker_entries),
        tickers=ticker_entries,
    )


def patch_calibration_paths(monkeypatch, tmp_path) -> None:
    """Redirect calibration history and pointer files into a temporary test directory."""

    calibration_dir = tmp_path / 'calibration'
    history_dir = calibration_dir / 'history'
    default_path = calibration_dir / 'activity_thresholds.json'
    active_state_path = calibration_dir / 'active_state.json'

    monkeypatch.setattr(calibration_store_module, 'CALIBRATION_DIR', calibration_dir)
    monkeypatch.setattr(calibration_store_module, 'CALIBRATION_HISTORY_DIR', history_dir)
    monkeypatch.setattr(calibration_store_module, 'DEFAULT_CALIBRATION_PATH', default_path)
    monkeypatch.setattr(calibration_store_module, 'ACTIVE_CALIBRATION_STATE_PATH', active_state_path)
    monkeypatch.setattr(activity_monitor_module, 'DEFAULT_CALIBRATION_PATH', default_path)


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


def test_runtime_config_loader_reads_direct_calibration_json(tmp_path):
    calibration_path = tmp_path / 'activity_thresholds.json'
    snapshot = build_snapshot('run-1')
    write_calibration_snapshot(snapshot, calibration_path)

    configs = load_runtime_configs(calibration_path=calibration_path)

    assert len(configs) == 1
    assert configs[0].ticker == 'BTCUSDC'
    assert configs[0].max_trade_count == 20


def test_record_calibration_run_writes_history_and_active_state(monkeypatch, tmp_path):
    patch_calibration_paths(monkeypatch, tmp_path)
    snapshot = build_snapshot('20260406T080000Z')

    history_path, state = record_calibration_run(snapshot, retention_days=5)

    assert history_path.exists()
    assert state.latest_run_id == snapshot.run_id
    assert state.active_run_id == snapshot.run_id
    assert state.activation_mode == 'auto'
    assert load_calibration_snapshot(calibration_store_module.DEFAULT_CALIBRATION_PATH).run_id == snapshot.run_id
    assert load_active_calibration_state(calibration_store_module.ACTIVE_CALIBRATION_STATE_PATH).active_run_id == snapshot.run_id


def test_manual_activation_persists_across_future_recalculations(monkeypatch, tmp_path):
    patch_calibration_paths(monkeypatch, tmp_path)
    first = build_snapshot('20260406T080000Z')
    second = build_snapshot('20260406T083000Z')
    third = build_snapshot('20260406T090000Z')

    record_calibration_run(first, retention_days=5)
    record_calibration_run(second, retention_days=5)
    activate_calibration_run(first.run_id)
    manual_state = load_active_calibration_state()

    assert manual_state.activation_mode == 'manual'
    assert manual_state.active_run_id == first.run_id
    assert manual_state.latest_run_id == second.run_id

    record_calibration_run(third, retention_days=5)
    state = load_active_calibration_state()

    assert state.activation_mode == 'manual'
    assert state.active_run_id == first.run_id
    assert state.latest_run_id == third.run_id
    assert load_calibration_snapshot(calibration_store_module.DEFAULT_CALIBRATION_PATH).run_id == first.run_id


def test_auto_mode_aligns_active_to_latest(monkeypatch, tmp_path):
    patch_calibration_paths(monkeypatch, tmp_path)
    first = build_snapshot('20260406T080000Z')
    second = build_snapshot('20260406T083000Z')

    record_calibration_run(first, retention_days=5)
    record_calibration_run(second, retention_days=5)
    activate_calibration_run(first.run_id)

    state = set_activation_mode('auto')

    assert state.activation_mode == 'auto'
    assert state.active_run_id == second.run_id
    assert state.latest_run_id == second.run_id
    assert load_calibration_snapshot(calibration_store_module.DEFAULT_CALIBRATION_PATH).run_id == second.run_id


def test_auto_mode_persists_selected_archive_hours(monkeypatch, tmp_path):
    patch_calibration_paths(monkeypatch, tmp_path)
    snapshot = build_snapshot('20260406T080000Z')
    record_calibration_run(snapshot, retention_days=5)

    state = set_activation_mode('auto', auto_archive_hours=3)

    assert state.activation_mode == 'auto'
    assert state.auto_archive_hours == 3
    assert load_active_calibration_state().auto_archive_hours == 3


def test_run_auto_archive_calibration_activates_latest_archive_period(monkeypatch, tmp_path):
    active_state = ActiveCalibrationState(
        activation_mode='auto',
        auto_archive_hours=3,
        updated_at='2026-04-06T08:00:00Z',
    )
    latest_period = calibrate_activity_module.ArchivePeriod(
        period_id='20260406T090000Z',
        nominal_end_time=datetime(2026, 4, 6, 9, 0, 0, tzinfo=timezone.utc),
        effective_end_time=datetime(2026, 4, 6, 9, 0, 0, tzinfo=timezone.utc),
    )
    computed_snapshot = build_snapshot(latest_period.period_id)
    activation_calls: list[dict] = []

    monkeypatch.setattr(calibrate_activity_module, 'load_active_calibration_state', lambda: active_state)
    monkeypatch.setattr(calibrate_activity_module, 'latest_archive_period', lambda archive_root, tickers: latest_period)
    monkeypatch.setattr(
        calibrate_activity_module,
        'compute_archive_period_snapshot_for_hours',
        lambda tickers, **kwargs: computed_snapshot,
    )

    def fake_activate_runtime_calibration_snapshot(snapshot, **kwargs):
        activation_calls.append(kwargs)
        return active_state.model_copy(update={
            'active_archive_period_id': kwargs['archive_period_id'],
            'active_archive_hours': kwargs['archive_hours'],
        })

    monkeypatch.setattr(
        calibrate_activity_module,
        'activate_runtime_calibration_snapshot',
        fake_activate_runtime_calibration_snapshot,
    )

    result = calibrate_activity_module.run_auto_archive_calibration(
        ['btcusdc'],
        archive_root=tmp_path,
        output_path=tmp_path / 'activity_thresholds.json',
        sampling_interval_ms=1000,
        lower_percentile=0.2,
        upper_percentile=0.8,
        window_ms=10000,
        min_sample_count=100,
    )

    assert result is not None
    assert result[0] == computed_snapshot
    assert result[1] == latest_period
    assert activation_calls == [{
        'archive_period_id': latest_period.period_id,
        'archive_period_end': calibration_store_module.isoformat_utc(latest_period.nominal_end_time),
        'archive_hours': 3,
        'activation_mode': 'auto',
    }]


def test_resolve_active_calibration_snapshot_falls_back_to_history(monkeypatch, tmp_path):
    patch_calibration_paths(monkeypatch, tmp_path)
    snapshot = build_snapshot('20260406T080000Z')
    record_calibration_run(snapshot, retention_days=5)
    calibration_store_module.DEFAULT_CALIBRATION_PATH.unlink()

    resolved = resolve_active_calibration_snapshot()

    assert resolved is not None
    assert resolved.run_id == snapshot.run_id


def test_prune_history_keeps_active_run(monkeypatch, tmp_path):
    patch_calibration_paths(monkeypatch, tmp_path)
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    old_active = build_snapshot('20260327T080000Z', generated_at=old_time)
    old_latest = build_snapshot('20260327T083000Z', generated_at=old_time)

    record_calibration_run(old_active, retention_days=5)
    activate_calibration_run(old_active.run_id)
    record_calibration_run(old_latest, retention_days=5)
    calibration_store_module.prune_calibration_history(retention_days=5)

    run_ids = [snapshot.run_id for snapshot in list_calibration_runs()]
    assert old_active.run_id in run_ids
    assert old_latest.run_id not in run_ids


def test_run_calibration_marks_reused_entries_from_previous_run(monkeypatch, tmp_path):
    previous_snapshot = build_snapshot(
        '20260406T070000Z',
        tickers=[build_ticker_entry('ETHUSDC')],
    )
    previous_path = tmp_path / 'activity_thresholds.json'
    write_calibration_snapshot(previous_snapshot, previous_path)
    fixed_now = datetime(2026, 4, 6, 8, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(calibrate_activity_module, 'utc_now', lambda: fixed_now)

    def fake_calibrate_ticker(ticker: str, **kwargs) -> CalibrationTickerEntry:
        if ticker == 'btcusdc':
            return build_ticker_entry('BTCUSDC')
        raise ValueError('not enough samples')

    monkeypatch.setattr(calibrate_activity_module, 'calibrate_ticker', fake_calibrate_ticker)

    snapshot = run_calibration(
        ['btcusdc', 'ethusdc'],
        archive_root=tmp_path,
        output_path=previous_path,
        lookback_minutes=120,
        sampling_interval_ms=1000,
        lower_percentile=0.2,
        upper_percentile=0.8,
        window_ms=10000,
        min_sample_count=100,
    )

    entries = {entry.ticker: entry for entry in snapshot.tickers}
    assert entries['BTCUSDC'].entry_status == 'fresh'
    assert entries['BTCUSDC'].source_run_id is None
    assert entries['ETHUSDC'].entry_status == 'reused'
    assert entries['ETHUSDC'].source_run_id == previous_snapshot.run_id
    assert snapshot.fresh_entry_count == 1
    assert snapshot.reused_entry_count == 1


def test_monitor_view_model_defaults_to_active_run(monkeypatch, tmp_path):
    patch_calibration_paths(monkeypatch, tmp_path)
    first = build_snapshot('20260406T080000Z')
    second = build_snapshot('20260406T083000Z')
    record_calibration_run(first, retention_days=5)
    record_calibration_run(second, retention_days=5)
    activate_calibration_run(first.run_id)
    monitor_app.calibration_panel_state['selected_run_id'] = None
    monitor_app.calibration_panel_state['notice'] = ''

    view_model = monitor_app.resolve_calibration_view_model()
    latest_label = monitor_app.build_calibration_option_label(second, load_active_calibration_state())
    active_label = monitor_app.build_calibration_option_label(first, load_active_calibration_state())

    assert view_model['selected_run_id'] == first.run_id
    assert view_model['selected_run'].run_id == first.run_id
    assert 'LATEST' in latest_label
    assert 'ACTIVE' in active_label


def test_calibration_table_rows_show_reused_status():
    snapshot = build_snapshot(
        '20260406T080000Z',
        tickers=[build_ticker_entry('BTCUSDC', entry_status='reused', source_run_id='20260406T070000Z')],
    )

    rows = monitor_app.calibration_table_rows(snapshot)

    assert rows[0]['status'] == 'Reused'
    assert rows[0]['ticker'] == 'BTCUSDC'
