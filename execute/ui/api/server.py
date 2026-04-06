"""Browser-safe bridge for the execute React UI.

This adapter preserves the existing execute Redis contracts and command payloads.
It only exposes snapshot reads, WebSocket updates, and command publishing.
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import redis
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from execute.trade.dashboard_state import build_dashboard_snapshot
from market_data.channels import EXECUTION_DASHBOARD_UPDATES_CHANNEL

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

sync_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
ws_clients: set[WebSocket] = set()


class CommandRequest(BaseModel):
    action: str
    ticker: str
    side: str | None = None
    limit_price: float | str | None = None
    initiated_by: str | None = None
    control_mode: str | None = None
    stop_price: float | str | None = None


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


def _snapshot_payload() -> dict[str, Any]:
    return build_dashboard_snapshot(sync_redis)


async def _broadcast_snapshot(message_type: str) -> None:
    payload = json.dumps({
        'type': message_type,
        'payload': _snapshot_payload(),
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
    await pubsub.subscribe(EXECUTION_DASHBOARD_UPDATES_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message and message.get('type') == 'message':
                await _broadcast_snapshot('update')
    finally:
        await pubsub.close()
        await client.aclose()


@app.get('/api/snapshot')
def get_snapshot():
    return _snapshot_payload()


@app.post('/api/commands')
def post_command(command: CommandRequest):
    payload = command.model_dump(exclude_none=True)
    if not payload['action'] or not payload['ticker']:
        raise HTTPException(status_code=400, detail='action and ticker are required')

    sync_redis.publish('execution_commands', json.dumps(payload))
    return {'ok': True, 'payload': payload}


@app.websocket('/ws/execute')
async def websocket_execute(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        await ws.send_text(json.dumps({
            'type': 'snapshot',
            'payload': _snapshot_payload(),
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(ws)
