"""Thin read-only API bridge exposing Redis monitor data and calibration actions to the React UI."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import redis
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from market_data.channels import (
    MARKET_DATA_UPDATES_CHANNEL,
    MONITOR_DASHBOARD_UPDATES_CHANNEL,
    activity_snapshots_key,
    latest_trade_event_key,
    minute_logs_key,
    rolling_metrics_key,
)
from monitor.activity_metrics import ROLLING_WINDOW_MS
from monitor.calibrate_activity import (
    DEFAULT_ARCHIVE_ROOT,
    DEFAULT_CALIBRATION_PATH,
    DEFAULT_LOWER_PERCENTILE,
    DEFAULT_MIN_SAMPLE_COUNT,
    DEFAULT_SAMPLING_INTERVAL_MS,
    DEFAULT_UPPER_PERCENTILE,
    archive_periods as list_archive_periods,
    compute_archive_period_snapshot_for_hours,
    compute_latest_archive_period_snapshot_for_hours,
)
from monitor.calibration_store import (
    activate_runtime_calibration_snapshot,
    isoformat_utc,
    load_active_calibration_state,
    resolve_active_calibration_snapshot,
    set_activation_mode,
)

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
CONFIG_PATH = ROOT_DIR / 'tickers_config.json'

sync_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

ws_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(_application: FastAPI):
    task = asyncio.create_task(_redis_subscriber())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

def _load_tickers() -> list[str]:
    with open(CONFIG_PATH) as f:
        return [item['ticker'].lower() for item in json.load(f)]

def _redis_list(key: str, limit: int = 60) -> list[dict]:
    return json.loads(sync_redis.get(key) or '[]')[:limit]

def _redis_latest(key: str) -> dict:
    rows = _redis_list(key, limit=60)
    return rows[-1] if rows else {}

def _latest_trade(ticker: str) -> dict:
    payload = sync_redis.get(latest_trade_event_key(ticker))
    return json.loads(payload) if payload else {}


def _overview_snapshot() -> list[dict]:
    tickers = _load_tickers()
    return [
        {
            'ticker': ticker.upper(),
            'rolling': _redis_latest(rolling_metrics_key(ticker)),
            'latest_trade': _latest_trade(ticker),
            'setup': _redis_latest(activity_snapshots_key(ticker)),
            'minute': _redis_latest(minute_logs_key(ticker)),
        }
        for ticker in tickers
    ]


def _monitor_snapshot_payload() -> dict:
    state = load_active_calibration_state()
    return {
        'overview': _overview_snapshot(),
        'rolling': _redis_list('rolling_metrics_logs'),
        'setups': _redis_list('trap_logs'),
        'minutes': _redis_list('minute_logs'),
        'calibrationState': state.model_dump() if state else None,
    }


async def _broadcast_monitor_snapshot(message_type: str) -> None:
    payload = json.dumps({
        'type': message_type,
        'payload': _monitor_snapshot_payload(),
    })
    disconnected: set[WebSocket] = set()
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)
    ws_clients.difference_update(disconnected)

async def _redis_subscriber() -> None:
    client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(MONITOR_DASHBOARD_UPDATES_CHANNEL, MARKET_DATA_UPDATES_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message and message.get('type') == 'message':
                await _broadcast_monitor_snapshot('update')
    finally:
        await pubsub.close()
        await client.aclose()


@app.get('/api/tickers')
def get_tickers():
    with open(CONFIG_PATH) as f:
        return json.load(f)

@app.get('/api/overview')
def get_overview():
    return _overview_snapshot()

@app.get('/api/feeds/rolling')
def get_rolling_feed():
    return _redis_list('rolling_metrics_logs')

@app.get('/api/feeds/setups')
def get_setup_feed():
    return _redis_list('trap_logs')

@app.get('/api/feeds/minutes')
def get_minute_feed():
    return _redis_list('minute_logs')

@app.get('/api/calibration/state')
def get_calibration_state():
    state = load_active_calibration_state()
    return state.model_dump() if state else None

@app.get('/api/calibration/periods')
def get_calibration_periods():
    tickers = _load_tickers()
    periods = list_archive_periods(Path(DEFAULT_ARCHIVE_ROOT), tickers)
    return [
        {
            'period_id': p.period_id,
            'nominal_end_time': p.nominal_end_time.isoformat(),
            'effective_end_time': p.effective_end_time.isoformat(),
        }
        for p in periods
    ]

@app.get('/api/calibration/active-snapshot')
def get_active_snapshot():
    snapshot = resolve_active_calibration_snapshot()
    return snapshot.model_dump() if snapshot else None

class PreviewRequest(BaseModel):
    period_id: str
    archive_hours: int = 2

@app.post('/api/calibration/preview')
def post_calibration_preview(req: PreviewRequest):
    tickers = _load_tickers()
    periods = list_archive_periods(Path(DEFAULT_ARCHIVE_ROOT), tickers)
    period = next((p for p in periods if p.period_id == req.period_id), None)
    if period is None:
        return {'error': 'Archive period not found'}
    try:
        snapshot = compute_archive_period_snapshot_for_hours(
            tickers,
            archive_root=Path(DEFAULT_ARCHIVE_ROOT),
            output_path=Path(DEFAULT_CALIBRATION_PATH),
            archive_hours=req.archive_hours,
            sampling_interval_ms=DEFAULT_SAMPLING_INTERVAL_MS,
            lower_percentile=DEFAULT_LOWER_PERCENTILE,
            upper_percentile=DEFAULT_UPPER_PERCENTILE,
            window_ms=ROLLING_WINDOW_MS,
            min_sample_count=DEFAULT_MIN_SAMPLE_COUNT,
            archive_period=period,
        )
        return snapshot.model_dump()
    except Exception as exc:
        return {'error': str(exc)}

class ActivateRequest(BaseModel):
    period_id: str
    archive_hours: int = 2

@app.post('/api/calibration/activate')
def post_calibration_activate(req: ActivateRequest):
    tickers = _load_tickers()
    periods = list_archive_periods(Path(DEFAULT_ARCHIVE_ROOT), tickers)
    period = next((p for p in periods if p.period_id == req.period_id), None)
    if period is None:
        return {'error': 'Archive period not found'}
    try:
        snapshot = compute_archive_period_snapshot_for_hours(
            tickers,
            archive_root=Path(DEFAULT_ARCHIVE_ROOT),
            output_path=Path(DEFAULT_CALIBRATION_PATH),
            archive_hours=req.archive_hours,
            sampling_interval_ms=DEFAULT_SAMPLING_INTERVAL_MS,
            lower_percentile=DEFAULT_LOWER_PERCENTILE,
            upper_percentile=DEFAULT_UPPER_PERCENTILE,
            window_ms=ROLLING_WINDOW_MS,
            min_sample_count=DEFAULT_MIN_SAMPLE_COUNT,
            archive_period=period,
        )
        state = activate_runtime_calibration_snapshot(
            snapshot,
            archive_period_id=period.period_id,
            archive_period_end=isoformat_utc(period.nominal_end_time),
            archive_hours=req.archive_hours,
        )
        return {'snapshot': snapshot.model_dump(), 'state': state.model_dump()}
    except Exception as exc:
        return {'error': str(exc)}

class ModeRequest(BaseModel):
    mode: str
    archive_hours: int = 2

@app.post('/api/calibration/mode')
def post_calibration_mode(req: ModeRequest):
    state = set_activation_mode(req.mode, auto_archive_hours=req.archive_hours)
    result: dict = {'state': state.model_dump()}
    if req.mode == 'auto':
        tickers = _load_tickers()
        try:
            snapshot, period = compute_latest_archive_period_snapshot_for_hours(
                tickers,
                archive_root=Path(DEFAULT_ARCHIVE_ROOT),
                output_path=Path(DEFAULT_CALIBRATION_PATH),
                archive_hours=req.archive_hours,
                sampling_interval_ms=DEFAULT_SAMPLING_INTERVAL_MS,
                lower_percentile=DEFAULT_LOWER_PERCENTILE,
                upper_percentile=DEFAULT_UPPER_PERCENTILE,
                window_ms=ROLLING_WINDOW_MS,
                min_sample_count=DEFAULT_MIN_SAMPLE_COUNT,
            )
            state = activate_runtime_calibration_snapshot(
                snapshot,
                archive_period_id=period.period_id,
                archive_period_end=isoformat_utc(period.nominal_end_time),
                archive_hours=req.archive_hours,
                activation_mode='auto',
            )
            result = {'state': state.model_dump(), 'snapshot': snapshot.model_dump()}
        except Exception as exc:
            result['auto_error'] = str(exc)
    return result

@app.websocket('/ws/monitor')
async def websocket_monitor(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        await ws.send_text(json.dumps({
            'type': 'snapshot',
            'payload': _monitor_snapshot_payload(),
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(ws)
