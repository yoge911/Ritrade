"""Persist immutable calibration runs plus the active/latest runtime selection state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parents[1]
CALIBRATION_DIR = ROOT_DIR / 'calibration'
CALIBRATION_HISTORY_DIR = CALIBRATION_DIR / 'history'
DEFAULT_CALIBRATION_PATH = CALIBRATION_DIR / 'activity_thresholds.json'
ACTIVE_CALIBRATION_STATE_PATH = CALIBRATION_DIR / 'active_state.json'
CALIBRATION_SCHEMA_VERSION = 1
ActivationMode = Literal['auto', 'manual']
EntryStatus = Literal['fresh', 'reused']


class ThresholdSet(BaseModel):
    """Volume, trade-count, and volatility thresholds used by activity qualification."""

    min_volume_threshold: float
    max_volume_threshold: float
    min_trade_count: int
    max_trade_count: int
    min_std_dev: float
    max_std_dev: float


class CalibrationSourceInfo(BaseModel):
    """Provenance for the archive slice that produced a ticker calibration entry."""

    type: str
    files: int
    first_event_time_ms: int | None = None
    last_event_time_ms: int | None = None


class CalibrationTickerEntry(BaseModel):
    """Per-ticker calibration payload together with freshness and fallback provenance."""

    ticker: str
    window_ms: int
    sampling_interval_ms: int
    recalculated_at: str
    lookback_duration_minutes: int
    sample_count: int
    lower_percentile: float
    upper_percentile: float
    source: CalibrationSourceInfo
    thresholds: ThresholdSet
    entry_status: EntryStatus = 'fresh'
    source_run_id: str | None = None


class CalibrationSnapshot(BaseModel):
    """Immutable calibration run written to history and optionally mirrored for runtime."""

    schema_version: int = CALIBRATION_SCHEMA_VERSION
    run_id: str
    metric_version: int
    generated_at: str
    fresh_entry_count: int = 0
    reused_entry_count: int = 0
    tickers: list[CalibrationTickerEntry]


class ActiveCalibrationState(BaseModel):
    """Authoritative pointer describing which run is latest and which run is active."""

    activation_mode: ActivationMode = 'auto'
    auto_archive_hours: int = 2
    active_run_id: str | None = None
    latest_run_id: str | None = None
    updated_at: str
    activated_at: str | None = None
    active_archive_period_id: str | None = None
    active_archive_period_end: str | None = None
    active_archive_hours: int | None = None
    active_archive_computed_at: str | None = None


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    """Serialize a datetime as a second-precision UTC ISO-8601 string."""

    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_utc_timestamp(value: str) -> datetime:
    """Parse a stored UTC ISO-8601 timestamp back into a timezone-aware datetime."""

    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def history_snapshot_path(run_id: str) -> Path:
    """Return the immutable history path for a calibration run id."""

    return CALIBRATION_HISTORY_DIR / f'{run_id}.json'


def load_calibration_snapshot(path: Path | None = None) -> CalibrationSnapshot | None:
    """Load a calibration snapshot from disk, defaulting to the runtime mirror path."""

    calibration_path = path or DEFAULT_CALIBRATION_PATH
    if not calibration_path.exists():
        return None

    with calibration_path.open('r') as calibration_file:
        return CalibrationSnapshot.model_validate(json.load(calibration_file))


def write_calibration_snapshot(snapshot: CalibrationSnapshot, path: Path | None = None) -> Path:
    """Write a calibration snapshot atomically to the requested path."""

    calibration_path = path or DEFAULT_CALIBRATION_PATH
    _write_json_atomic(calibration_path, snapshot.model_dump())
    return calibration_path


def load_active_calibration_state(path: Path | None = None) -> ActiveCalibrationState | None:
    """Load the authoritative active/latest calibration state record."""

    state_path = path or ACTIVE_CALIBRATION_STATE_PATH
    if not state_path.exists():
        return None
    with state_path.open('r') as state_file:
        return ActiveCalibrationState.model_validate(json.load(state_file))


def write_active_calibration_state(state: ActiveCalibrationState, path: Path | None = None) -> Path:
    """Persist the authoritative active/latest calibration state atomically."""

    state_path = path or ACTIVE_CALIBRATION_STATE_PATH
    _write_json_atomic(state_path, state.model_dump())
    return state_path


def write_calibration_run(snapshot: CalibrationSnapshot) -> Path:
    """Write a new immutable calibration run to history and reject duplicate run ids."""

    run_path = history_snapshot_path(snapshot.run_id)
    if run_path.exists():
        raise ValueError(f'Calibration run already exists: {snapshot.run_id}')
    _write_json_atomic(run_path, snapshot.model_dump())
    return run_path


def load_calibration_run(run_id: str) -> CalibrationSnapshot | None:
    """Load a specific immutable calibration run by its stable run id."""

    run_path = history_snapshot_path(run_id)
    return load_calibration_snapshot(run_path)


def list_calibration_runs() -> list[CalibrationSnapshot]:
    """Return all immutable calibration runs sorted newest-first."""

    if not CALIBRATION_HISTORY_DIR.exists():
        return []

    runs: list[CalibrationSnapshot] = []
    for path in CALIBRATION_HISTORY_DIR.glob('*.json'):
        snapshot = load_calibration_snapshot(path)
        if snapshot is not None:
            runs.append(snapshot)
    runs.sort(key=lambda snapshot: snapshot.generated_at, reverse=True)
    return runs


def resolve_active_calibration_snapshot() -> CalibrationSnapshot | None:
    """Resolve the active calibration via the pointer file, falling back to the mirror file."""

    state = load_active_calibration_state()
    if state and state.active_run_id:
        active_snapshot = load_calibration_run(state.active_run_id)
        if active_snapshot is not None:
            return active_snapshot
    return load_calibration_snapshot(DEFAULT_CALIBRATION_PATH)


def record_calibration_run(
    snapshot: CalibrationSnapshot,
    *,
    retention_days: int,
) -> tuple[Path, ActiveCalibrationState]:
    """Record a new run, update latest/active state, mirror the active run, and prune history."""

    write_calibration_run(snapshot)

    now = snapshot.generated_at
    state = load_active_calibration_state() or ActiveCalibrationState(updated_at=now)
    auto_archive_hours = state.auto_archive_hours
    active_run_id = state.active_run_id
    activated_at = state.activated_at
    active_archive_period_id = state.active_archive_period_id
    active_archive_period_end = state.active_archive_period_end
    active_archive_hours = state.active_archive_hours
    active_archive_computed_at = state.active_archive_computed_at
    dynamic_runtime_active = active_run_id is None and active_archive_period_id is not None

    if state.activation_mode == 'auto' or (active_run_id is None and not dynamic_runtime_active):
        active_run_id = snapshot.run_id
        activated_at = now
        active_archive_period_id = None
        active_archive_period_end = None
        active_archive_hours = None
        active_archive_computed_at = None

    updated_state = ActiveCalibrationState(
        activation_mode=state.activation_mode,
        auto_archive_hours=auto_archive_hours,
        active_run_id=active_run_id,
        latest_run_id=snapshot.run_id,
        updated_at=now,
        activated_at=activated_at,
        active_archive_period_id=active_archive_period_id,
        active_archive_period_end=active_archive_period_end,
        active_archive_hours=active_archive_hours,
        active_archive_computed_at=active_archive_computed_at,
    )
    write_active_calibration_state(updated_state)
    _sync_runtime_snapshot(updated_state.active_run_id)
    prune_calibration_history(retention_days=retention_days, active_run_id=updated_state.active_run_id)
    return history_snapshot_path(snapshot.run_id), updated_state


def activate_calibration_run(run_id: str) -> ActiveCalibrationState:
    """Activate a historical run explicitly and switch the system into manual mode."""

    snapshot = load_calibration_run(run_id)
    if snapshot is None:
        raise ValueError(f'Calibration run not found: {run_id}')

    now = isoformat_utc(utc_now())
    current_state = load_active_calibration_state() or ActiveCalibrationState(updated_at=now)
    updated_state = ActiveCalibrationState(
        activation_mode='manual',
        auto_archive_hours=current_state.auto_archive_hours,
        active_run_id=run_id,
        latest_run_id=current_state.latest_run_id or run_id,
        updated_at=now,
        activated_at=now,
        active_archive_period_id=None,
        active_archive_period_end=None,
        active_archive_hours=None,
        active_archive_computed_at=None,
    )
    write_active_calibration_state(updated_state)
    _sync_runtime_snapshot(run_id)
    return updated_state


def activate_runtime_calibration_snapshot(
    snapshot: CalibrationSnapshot,
    *,
    archive_period_id: str,
    archive_period_end: str,
    archive_hours: int,
    activation_mode: ActivationMode = 'manual',
) -> ActiveCalibrationState:
    """Activate a runtime-only calibration snapshot for a selected archive period and hour window."""

    now = isoformat_utc(utc_now())
    current_state = load_active_calibration_state() or ActiveCalibrationState(updated_at=now)
    updated_state = ActiveCalibrationState(
        activation_mode=activation_mode,
        auto_archive_hours=current_state.auto_archive_hours,
        active_run_id=None,
        latest_run_id=current_state.latest_run_id,
        updated_at=now,
        activated_at=now,
        active_archive_period_id=archive_period_id,
        active_archive_period_end=archive_period_end,
        active_archive_hours=archive_hours,
        active_archive_computed_at=snapshot.generated_at,
    )
    write_calibration_snapshot(snapshot, DEFAULT_CALIBRATION_PATH)
    write_active_calibration_state(updated_state)
    return updated_state


def set_activation_mode(mode: ActivationMode, *, auto_archive_hours: int | None = None) -> ActiveCalibrationState:
    """Change activation mode and optionally realign active to latest when auto mode is enabled."""

    current_state = load_active_calibration_state() or ActiveCalibrationState(updated_at=isoformat_utc(utc_now()))
    now = isoformat_utc(utc_now())
    auto_archive_hours = max(int(auto_archive_hours), 1) if auto_archive_hours is not None else current_state.auto_archive_hours
    active_run_id = current_state.active_run_id
    activated_at = current_state.activated_at
    active_archive_period_id = current_state.active_archive_period_id
    active_archive_period_end = current_state.active_archive_period_end
    active_archive_hours = current_state.active_archive_hours
    active_archive_computed_at = current_state.active_archive_computed_at

    if mode == 'auto' and current_state.latest_run_id:
        active_run_id = current_state.latest_run_id
        activated_at = now
        active_archive_period_id = None
        active_archive_period_end = None
        active_archive_hours = None
        active_archive_computed_at = None

    updated_state = ActiveCalibrationState(
        activation_mode=mode,
        auto_archive_hours=auto_archive_hours,
        active_run_id=active_run_id,
        latest_run_id=current_state.latest_run_id,
        updated_at=now,
        activated_at=activated_at,
        active_archive_period_id=active_archive_period_id,
        active_archive_period_end=active_archive_period_end,
        active_archive_hours=active_archive_hours,
        active_archive_computed_at=active_archive_computed_at,
    )
    write_active_calibration_state(updated_state)
    _sync_runtime_snapshot(updated_state.active_run_id)
    return updated_state


def prune_calibration_history(*, retention_days: int, active_run_id: str | None = None) -> None:
    """Delete expired history runs while preserving the currently active run."""

    if retention_days <= 0 or not CALIBRATION_HISTORY_DIR.exists():
        return

    cutoff = utc_now() - timedelta(days=retention_days)
    keep_run_id = active_run_id
    if keep_run_id is None:
        state = load_active_calibration_state()
        keep_run_id = state.active_run_id if state else None

    for path in CALIBRATION_HISTORY_DIR.glob('*.json'):
        snapshot = load_calibration_snapshot(path)
        if snapshot is None:
            continue
        if snapshot.run_id == keep_run_id:
            continue
        if parse_utc_timestamp(snapshot.generated_at) < cutoff:
            path.unlink(missing_ok=True)


def _sync_runtime_snapshot(active_run_id: str | None) -> None:
    """Mirror the active immutable run into the legacy runtime snapshot path."""

    if active_run_id is None:
        return
    snapshot = load_calibration_run(active_run_id)
    if snapshot is None:
        raise ValueError(f'Active calibration run not found: {active_run_id}')
    write_calibration_snapshot(snapshot, DEFAULT_CALIBRATION_PATH)


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON to disk with a temp-file replace so readers never see partial state."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f'{path.suffix}.tmp')
    with temp_path.open('w') as output_file:
        json.dump(payload, output_file, indent=2)
        output_file.write('\n')
    temp_path.replace(path)
