import asyncio
import json
import os
import sys
from datetime import datetime

import numpy as np
import redis
from pydantic import BaseModel

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from market_data.channels import (
    GLOBAL_MINUTE_LOGS_KEY,
    GLOBAL_ROLLING_METRICS_LOGS_KEY,
    GLOBAL_TRAP_LOGS_KEY,
    activity_snapshots_key,
    minute_logs_key,
    rolling_metrics_key,
    trade_events_channel,
)
from market_data.models import TradeEvent

MAX_LOG_ENTRIES = 60
ROLLING_WINDOW_MS = 10000
QUALIFICATION_WINDOW_MS = 20000
ROLLING_LOG_RETENTION_MS = 120000


class TickerConfig(BaseModel):
    ticker: str
    min_volume_threshold: float
    max_volume_threshold: float
    min_trade_count: int
    max_trade_count: int
    min_std_dev: float
    max_std_dev: float


class ActivitySnapshot(BaseModel):
    ticker: str
    timestamp: str
    event_time_ms: int | None = None
    live_price: float | None = None
    is_qualified_activity: bool
    activity_score: float
    trades: int
    volume: float
    avg_price: float
    wap: float
    std_dev: float
    slope: float
    setup_start_time: str | None = None
    setup_end_time: str | None = None
    qualification_duration_ms: int | None = None
    trigger_reason: str | None = None


class MinuteSummary(BaseModel):
    ticker: str
    timestamp: str
    trades: int
    volume: float
    avg_price: float


class TickerState:
    def __init__(self, config: TickerConfig):
        self.config = config
        self.rolling_window_trades: list[TradeEvent] = []
        self.current_minute_trades: list[TradeEvent] = []
        self.activity_snapshots: list[ActivitySnapshot] = []
        self.minute_logs: list[MinuteSummary] = []
        self.rolling_metrics_logs: list[ActivitySnapshot] = []
        self.current_minute: datetime | None = None
        self.active_setup_start_time: int | None = None
        self.active_setup_trigger_reason: str | None = None
        self.active_setup_trades: list[TradeEvent] = []
        self.last_trigger_qualified = False

    def process_trade_event(self, event: TradeEvent) -> tuple[ActivitySnapshot, ActivitySnapshot | None, MinuteSummary | None]:
        """Update rolling metrics and finalize trigger-based setup snapshots when their window completes."""
        trade_minute = datetime.fromtimestamp(event.event_time / 1000).replace(second=0, microsecond=0)
        minute_summary: MinuteSummary | None = None

        if self.current_minute is None:
            self.current_minute = trade_minute

        if trade_minute != self.current_minute:
            minute_summary = generate_minute_data(self.current_minute, self.current_minute_trades, self.config.ticker)
            append_capped(self.minute_logs, minute_summary)
            self.current_minute = trade_minute
            self.current_minute_trades = []

        self.current_minute_trades.append(event)

        self.rolling_window_trades.append(event)
        cutoff_time = event.event_time - ROLLING_WINDOW_MS
        self.rolling_window_trades[:] = [trade for trade in self.rolling_window_trades if trade.event_time >= cutoff_time]

        rolling_snapshot = generate_activity_snapshot(event.event_time, self.rolling_window_trades, self.config)
        append_capped(self.rolling_metrics_logs, rolling_snapshot)
        prune_expired_snapshots(self.rolling_metrics_logs, event.event_time, retention_ms=ROLLING_LOG_RETENTION_MS)

        setup_triggered = False
        if (
            self.active_setup_start_time is None
            and rolling_snapshot.is_qualified_activity
            and not self.last_trigger_qualified
        ):
            self.active_setup_start_time = event.event_time
            self.active_setup_trigger_reason = 'rolling_snapshot_qualified'
            self.active_setup_trades = [event]
            setup_triggered = True

        if self.active_setup_start_time is not None and not setup_triggered:
            self.active_setup_trades.append(event)

        trap_snapshot: ActivitySnapshot | None = None
        if (
            self.active_setup_start_time is not None
            and event.event_time >= self.active_setup_start_time + QUALIFICATION_WINDOW_MS
        ):
            setup_cutoff = qualification_window_end(self.active_setup_start_time)
            trap_snapshot = generate_setup_snapshot(
                setup_cutoff,
                clip_setup_trades(self.active_setup_trades, setup_cutoff),
                self.config,
                self.active_setup_start_time,
                self.active_setup_trigger_reason,
            )
            append_capped(self.activity_snapshots, trap_snapshot)
            self.active_setup_start_time = None
            self.active_setup_trigger_reason = None
            self.active_setup_trades = []

        self.last_trigger_qualified = rolling_snapshot.is_qualified_activity

        return rolling_snapshot, trap_snapshot, minute_summary


class ActivityMonitor:
    def __init__(self, configs: list[TickerConfig], redis_client: redis.Redis | None = None) -> None:
        self.redis_client = redis_client or redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.states = {config.ticker.lower(): TickerState(config) for config in configs}
        self.global_trap_logs: list[dict] = []
        self.global_minute_logs: list[dict] = []
        self.global_rolling_metrics_logs: list[dict] = []

    def initialize_redis(self) -> None:
        """Clear all monitor Redis keys for every configured ticker on startup."""
        self.redis_client.delete(
            GLOBAL_TRAP_LOGS_KEY,
            GLOBAL_MINUTE_LOGS_KEY,
            GLOBAL_ROLLING_METRICS_LOGS_KEY,
        )
        for ticker in self.states:
            self.redis_client.delete(
                activity_snapshots_key(ticker),
                minute_logs_key(ticker),
                rolling_metrics_key(ticker),
            )
        print(f'✅ Redis initialized for {len(self.states)} monitor tickers.')

    def handle_trade_event(self, event: TradeEvent) -> None:
        """Route an incoming trade event to the correct ticker state and persist results to Redis."""
        state = self.states.get(event.symbol.lower())
        if not state:
            return

        rolling_snapshot, trap_snapshot, minute_summary = state.process_trade_event(event)
        append_capped(self.global_rolling_metrics_logs, rolling_snapshot.model_dump())
        prune_expired_dict_logs(
            self.global_rolling_metrics_logs,
            event.event_time,
            retention_ms=ROLLING_LOG_RETENTION_MS,
            timestamp_field='event_time_ms',
        )
        if trap_snapshot:
            append_capped(self.global_trap_logs, trap_snapshot.model_dump())
            print(f"\n📊 [{event.symbol.upper()}] Activity Snapshot Triggered @ {trap_snapshot.timestamp}")
        if minute_summary:
            append_capped(self.global_minute_logs, minute_summary.model_dump())
        self.save_state_to_redis(event.symbol.lower(), state)

    def save_state_to_redis(self, ticker: str, state: TickerState) -> None:
        """Write per-ticker and global log lists to Redis, capped at MAX_LOG_ENTRIES."""
        self.redis_client.set(
            activity_snapshots_key(ticker),
            json.dumps([entry.model_dump() for entry in state.activity_snapshots[-MAX_LOG_ENTRIES:]]),
        )
        self.redis_client.set(
            minute_logs_key(ticker),
            json.dumps([entry.model_dump() for entry in state.minute_logs[-MAX_LOG_ENTRIES:]]),
        )
        self.redis_client.set(
            rolling_metrics_key(ticker),
            json.dumps([entry.model_dump() for entry in state.rolling_metrics_logs]),
        )
        self.redis_client.set(GLOBAL_TRAP_LOGS_KEY, json.dumps(self.global_trap_logs[-MAX_LOG_ENTRIES:]))
        self.redis_client.set(GLOBAL_MINUTE_LOGS_KEY, json.dumps(self.global_minute_logs[-MAX_LOG_ENTRIES:]))
        self.redis_client.set(
            GLOBAL_ROLLING_METRICS_LOGS_KEY,
            json.dumps(self.global_rolling_metrics_logs),
        )

    async def consume_trade_events(self, ticker: str) -> None:
        """Subscribe to a ticker's Redis trade-event channel and dispatch messages in a polling loop."""
        pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(trade_events_channel(ticker))
        print(f'📡 Listening for normalized trade events on {trade_events_channel(ticker)}...')

        try:
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message.get('type') == 'message':
                    try:
                        event = TradeEvent.model_validate_json(message['data'])
                    except ValueError:
                        print(f'⚠️ Invalid trade event payload for {ticker}: {message["data"]}')
                    else:
                        self.handle_trade_event(event)
                await asyncio.sleep(0.05)
        finally:
            pubsub.close()


def append_capped(items: list, item, limit: int = MAX_LOG_ENTRIES) -> None:
    """Append an item and drop the oldest entry if the list exceeds limit."""
    items.append(item)
    if len(items) > limit:
        items.pop(0)


def prune_expired_snapshots(items: list[ActivitySnapshot], current_event_time: int, retention_ms: int) -> None:
    """Drop rolling snapshots older than the configured retention window."""
    cutoff_time = current_event_time - retention_ms
    items[:] = [item for item in items if item.event_time_ms is None or item.event_time_ms >= cutoff_time]


def prune_expired_dict_logs(items: list[dict], current_event_time: int, retention_ms: int, timestamp_field: str) -> None:
    """Drop serialized rolling logs older than the configured retention window."""
    cutoff_time = current_event_time - retention_ms
    items[:] = [item for item in items if item.get(timestamp_field) is None or item.get(timestamp_field) >= cutoff_time]


def load_configs() -> list[TickerConfig]:
    """Load and parse ticker configurations from tickers_config.json at the repo root."""
    config_path = os.path.join(ROOT_DIR, 'tickers_config.json')
    if not os.path.exists(config_path):
        print(f'⚠️  Config file not found at {config_path}')
        return []
    with open(config_path, 'r') as config_file:
        data = json.load(config_file)
    return [TickerConfig(**item) for item in data]


def format_timestamp(ms: int) -> str:
    """Convert a millisecond epoch timestamp to an HH:MM:SS.mmm string."""
    return datetime.fromtimestamp(ms / 1000).strftime('%H:%M:%S.%f')[:-3]


def format_minute(dt: datetime) -> str:
    """Format a datetime to a YYYY-MM-DD HH:MM:SS string for minute-boundary logs."""
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def calculate_wap(prices: list[float], quantities: list[float]) -> float:
    """Return the quantity-weighted average price, or 0 if total quantity is zero."""
    total_qty = sum(quantities)
    return sum(price * quantity for price, quantity in zip(prices, quantities)) / total_qty if total_qty else 0


def normalize_value(current_value: float, percentile_20: float, percentile_80: float) -> float:
    """Linearly scale current_value to [0, 1] using 20th–80th percentile bounds."""
    if current_value <= percentile_20:
        return 0.0
    if current_value >= percentile_80:
        return 1.0
    return (current_value - percentile_20) / (percentile_80 - percentile_20)


def generate_minute_data(current_minute: datetime, trades_window: list[TradeEvent], ticker: str) -> MinuteSummary:
    """Summarise all trades in the current window into a per-minute volume and price snapshot."""
    prices = [trade.price for trade in trades_window]
    quantities = [trade.quantity for trade in trades_window]
    total_volume = sum(quantities)
    return MinuteSummary(
        ticker=ticker.lower(),
        timestamp=format_minute(current_minute),
        trades=len(trades_window),
        volume=round(total_volume, 3),
        avg_price=round(np.mean(prices) if prices else 0, 5),
    )


def qualification_window_end(setup_start_time: int) -> int:
    """Return the inclusive millisecond cutoff for a setup qualification window."""
    return setup_start_time + QUALIFICATION_WINDOW_MS


def clip_setup_trades(trades: list[TradeEvent], setup_cutoff_time: int) -> list[TradeEvent]:
    """Keep only trades that belong to the intended setup qualification window."""
    return [trade for trade in trades if trade.event_time <= setup_cutoff_time]


def build_activity_snapshot(
    event_time: int,
    trades: list[TradeEvent],
    config: TickerConfig,
    *,
    setup_start_time: int | None = None,
    trigger_reason: str | None = None,
) -> ActivitySnapshot:
    """Compute WAP, std dev, slope, and a 0–1 activity score from any trade buffer."""
    prices = [trade.price for trade in trades]
    quantities = [trade.quantity for trade in trades]
    total_volume = sum(quantities)
    avg_price = np.mean(prices) if prices else 0
    std_dev = np.std(prices) if prices else 0
    slope = prices[-1] - prices[0] if len(prices) > 1 else 0
    wap = calculate_wap(prices, quantities)
    trade_count = len(trades)

    is_qualified_activity = False
    activity_score = 0.0

    if config.min_volume_threshold < total_volume < config.max_volume_threshold:
        if trade_count > config.min_trade_count and config.min_std_dev < std_dev < config.max_std_dev:
            is_qualified_activity = True
            normalized_volume = normalize_value(total_volume, config.min_volume_threshold, config.max_volume_threshold)
            normalized_std_dev = normalize_value(std_dev, config.min_std_dev, config.max_std_dev)
            normalized_trade_count = normalize_value(trade_count, config.min_trade_count, config.max_trade_count)
            activity_score = (normalized_volume + normalized_std_dev + normalized_trade_count) / 3

    return ActivitySnapshot(
        ticker=config.ticker.lower(),
        timestamp=format_timestamp(event_time),
        event_time_ms=event_time,
        live_price=round(prices[-1], 5) if prices else None,
        is_qualified_activity=is_qualified_activity,
        activity_score=round(activity_score, 5),
        trades=trade_count,
        volume=round(total_volume, 3),
        avg_price=round(avg_price, 5),
        wap=round(wap, 5),
        std_dev=round(std_dev, 5),
        slope=round(slope, 5),
        setup_start_time=format_timestamp(setup_start_time) if setup_start_time is not None else None,
        setup_end_time=format_timestamp(event_time) if setup_start_time is not None else None,
        qualification_duration_ms=(event_time - setup_start_time) if setup_start_time is not None else None,
        trigger_reason=trigger_reason,
    )


def generate_activity_snapshot(event_time: int, trades_window: list[TradeEvent], config: TickerConfig) -> ActivitySnapshot:
    """Compute a rolling metrics snapshot from the rolling 10-second trade window."""
    return build_activity_snapshot(event_time, trades_window, config)


def generate_setup_snapshot(
    event_time: int,
    setup_trades: list[TradeEvent],
    config: TickerConfig,
    setup_start_time: int,
    trigger_reason: str | None,
) -> ActivitySnapshot:
    """Compute a finalized setup snapshot from the full setup qualification buffer."""
    return build_activity_snapshot(
        event_time,
        setup_trades,
        config,
        setup_start_time=setup_start_time,
        trigger_reason=trigger_reason,
    )


async def main() -> None:
    """Load configs, initialize Redis, and run one consumer coroutine per configured ticker."""
    configs = load_configs()
    if not configs:
        print('❌ No tickers configured. Please ensure tickers_config.json is populated.')
        return

    monitor = ActivityMonitor(configs)
    monitor.initialize_redis()
    tasks = [monitor.consume_trade_events(config.ticker.lower()) for config in configs]
    print(f'🚀 Starting monitor consumers for {len(tasks)} tickers...')
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
