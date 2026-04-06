from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import redis


COMMAND_CHANNEL = 'execution_commands'
PINNED_SET_KEY = 'execution_pinned_tickers'
ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / 'tickers_config.json'

STATUS_FLOAT_FIELDS = {
    'live_price',
    'limit_price',
    'entry_price',
    'stop_price',
    'target_price',
    'pnl',
    'quantity',
    'risk_percent',
    'reward_percent',
}
STATUS_BOOL_FIELDS = {
    'is_pinned',
    'manual_override_active',
}


def load_tickers(config_path: str | Path = CONFIG_PATH) -> list[str]:
    with open(config_path, 'r') as f:
        return [item['ticker'].lower() for item in json.load(f)]


def load_json(redis_client: redis.Redis, key: str, limit: int = 60) -> list[dict[str, Any]]:
    return json.loads(redis_client.get(key) or '[]')[:limit]


def load_status(redis_client: redis.Redis, ticker: str) -> dict[str, str]:
    return redis_client.hgetall(f'{ticker}_status')


def pinned_tickers(redis_client: redis.Redis) -> list[str]:
    return sorted(redis_client.smembers(PINNED_SET_KEY))


def publish_command(redis_client: redis.Redis, action: str, ticker: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {'action': action, 'ticker': ticker}
    payload.update(extra)
    redis_client.publish(COMMAND_CHANNEL, json.dumps(payload))
    return payload


def latest_activity_snapshot(redis_client: redis.Redis, ticker: str) -> dict[str, Any]:
    snapshot = load_json(redis_client, f'{ticker}_activity_snapshots', limit=60)
    return snapshot[-1] if snapshot else {}


def latest_minute_snapshot(redis_client: redis.Redis, ticker: str) -> dict[str, Any]:
    minute = load_json(redis_client, f'{ticker}_minute_logs', limit=60)
    return minute[-1] if minute else {}


def latest_signal_rows(redis_client: redis.Redis, tickers: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pinned = set(pinned_tickers(redis_client))

    for ticker in tickers:
        activity = latest_activity_snapshot(redis_client, ticker)
        minute = latest_minute_snapshot(redis_client, ticker)
        rows.append({
            'ticker': ticker.upper(),
            'timestamp': activity.get('timestamp'),
            'qualified': 'Yes' if activity.get('is_qualified_activity') else 'No',
            'activity_score': parse_float(activity.get('activity_score')),
            'trades': parse_float(activity.get('trades')),
            'volume': parse_float(activity.get('volume')),
            'wap': parse_float(activity.get('wap')),
            'std_dev': parse_float(activity.get('std_dev')),
            'slope': parse_float(activity.get('slope')),
            'minute_timestamp': minute.get('timestamp'),
            'minute_trades': parse_float(minute.get('trades')),
            'minute_volume': parse_float(minute.get('volume')),
            'minute_avg_price': parse_float(minute.get('avg_price')),
            'is_pinned': ticker in pinned,
        })

    rows.sort(
        key=lambda row: row['activity_score'] if isinstance(row['activity_score'], (int, float)) else -1,
        reverse=True,
    )
    return rows


def parse_float(value: str | float | int | None) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes'}
    return bool(value)


def parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_status(status: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in status.items():
        if key in STATUS_FLOAT_FIELDS:
            normalized[key] = parse_float(value)
        elif key in STATUS_BOOL_FIELDS:
            normalized[key] = parse_bool(value)
        elif key == 'strategy_state':
            normalized[key] = parse_json(value)
        else:
            normalized[key] = value

    normalized.setdefault('state', 'idle')
    normalized.setdefault('control_mode', 'manual')
    normalized.setdefault('zone', 'Flat')
    normalized.setdefault('position', '')
    normalized.setdefault('strategy_state', {})
    normalized.setdefault('stop_mode', '')
    return normalized


def format_price(value: str | float | int | None) -> str:
    number = parse_float(value)
    return '—' if number is None else f'${number:.2f}'


def format_pnl(value: str | float | int | None) -> str:
    number = parse_float(value)
    if number is None:
        return '—'
    sign = '+' if number >= 0 else ''
    return f'{sign}{number:.2f}'


def format_metric(value: str | float | int | None, digits: int = 2) -> str:
    parsed = parse_float(value)
    if parsed is None:
        return '—' if value in (None, '') else str(value)
    return f'{parsed:.{digits}f}'


def pnl_class(value: str | float | int | None) -> str:
    number = parse_float(value)
    if number is None:
        return 'neutral'
    if number > 0:
        return 'profit'
    if number < 0:
        return 'loss'
    return 'neutral'


def score_class(value: object) -> str:
    if not isinstance(value, (int, float)):
        return 'signal-cold'
    if value >= 0.6:
        return 'signal-hot'
    if value >= 0.3:
        return 'signal-warm'
    return 'signal-cold'


def is_positive_signal(row: dict[str, Any]) -> bool:
    score = row.get('activity_score')
    return row.get('qualified') == 'Yes' or (isinstance(score, (int, float)) and score >= 0.3)


def build_manual_order_command(
    ticker: str,
    side: str,
    live_price: str | float | int | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if live_price in (None, ''):
        return None, f'{ticker.upper()} has no live price yet.'

    return {
        'action': 'place_limit_order',
        'ticker': ticker,
        'side': side,
        'limit_price': live_price,
        'initiated_by': 'manual',
        'control_mode': 'manual',
    }, None


def build_trailing_stop_command(
    ticker: str,
    live_price: str | float | int | None,
    position: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    current_price = parse_float(live_price)
    if current_price is None or position not in {'long', 'short'}:
        return None, f'{ticker.upper()} needs an active trade and live price for trailing stop.'

    trail_gap = 0.0015
    stop_price = current_price * (1 - trail_gap) if position == 'long' else current_price * (1 + trail_gap)
    return {
        'action': 'modify_stop',
        'ticker': ticker,
        'stop_price': round(stop_price, 2),
    }, None


def build_pinned_ticker_view(redis_client: redis.Redis, ticker: str) -> dict[str, Any]:
    status = normalize_status(load_status(redis_client, ticker))
    activity = latest_activity_snapshot(redis_client, ticker)
    score = parse_float(activity.get('activity_score'))
    qualified = bool(activity.get('is_qualified_activity'))
    return {
        'ticker': ticker.upper(),
        'status': status,
        'activity': {
            'timestamp': activity.get('timestamp'),
            'is_qualified_activity': qualified,
            'activity_score': score,
            'trades': parse_float(activity.get('trades')),
            'volume': parse_float(activity.get('volume')),
            'wap': parse_float(activity.get('wap')),
            'std_dev': parse_float(activity.get('std_dev')),
            'slope': parse_float(activity.get('slope')),
        },
        'badge_label': 'HOT' if qualified else 'WATCH',
        'score_class': score_class(score).replace('signal-', ''),
        'pnl_class': pnl_class(status.get('pnl')),
        'last_timestamp': activity.get('timestamp') or status.get('last_update') or '—',
    }


def build_dashboard_snapshot(redis_client: redis.Redis) -> dict[str, Any]:
    tickers = load_tickers()
    rows = latest_signal_rows(redis_client, tickers)
    pinned = [build_pinned_ticker_view(redis_client, ticker) for ticker in pinned_tickers(redis_client)]
    return {
        'tickers': tickers,
        'pinned': pinned,
        'activityRows': rows,
        'minuteRows': rows,
    }
