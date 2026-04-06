from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION_PATH = ROOT_DIR / 'calibration' / 'activity_thresholds.json'
CALIBRATION_SCHEMA_VERSION = 1


class ThresholdSet(BaseModel):
    min_volume_threshold: float
    max_volume_threshold: float
    min_trade_count: int
    max_trade_count: int
    min_std_dev: float
    max_std_dev: float


class CalibrationSourceInfo(BaseModel):
    type: str
    files: int
    first_event_time_ms: int | None = None
    last_event_time_ms: int | None = None


class CalibrationTickerEntry(BaseModel):
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


class CalibrationSnapshot(BaseModel):
    schema_version: int = CALIBRATION_SCHEMA_VERSION
    metric_version: int
    generated_at: str
    tickers: list[CalibrationTickerEntry]


def load_calibration_snapshot(path: Path | None = None) -> CalibrationSnapshot | None:
    calibration_path = path or DEFAULT_CALIBRATION_PATH
    if not calibration_path.exists():
        return None

    with calibration_path.open('r') as calibration_file:
        return CalibrationSnapshot.model_validate(json.load(calibration_file))


def write_calibration_snapshot(snapshot: CalibrationSnapshot, path: Path | None = None) -> Path:
    calibration_path = path or DEFAULT_CALIBRATION_PATH
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = calibration_path.with_suffix(f'{calibration_path.suffix}.tmp')
    with temp_path.open('w') as calibration_file:
        json.dump(snapshot.model_dump(), calibration_file, indent=2)
        calibration_file.write('\n')
    temp_path.replace(calibration_path)
    return calibration_path
