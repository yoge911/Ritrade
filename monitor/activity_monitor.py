import asyncio
import websockets
import json
import numpy as np
import redis
import os
from datetime import datetime
from pydantic import BaseModel

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Type alias: (timestamp_ms, price, quantity)
TradeEntry = tuple[int, float, float]


class TickerConfig(BaseModel):
    ticker: str
    min_volume_threshold: float
    max_volume_threshold: float
    min_trade_count: int
    max_trade_count: int
    min_std_dev: float
    max_std_dev: float


class ActivitySnapshot(BaseModel):
    timestamp: str
    is_qualified_activity: bool
    activity_score: float
    trades: int
    volume: float
    avg_price: float
    wap: float
    std_dev: float
    slope: float


class MinuteSummary(BaseModel):
    timestamp: str
    trades: int
    volume: float
    avg_price: float


class TickerState:
    def __init__(self, config: TickerConfig):
        self.config = config
        self.rolling_window_trades: list[TradeEntry] = []
        self.activity_snapshots: list[ActivitySnapshot] = []
        self.minute_logs: list[MinuteSummary] = []
        self.rolling_metrics_logs: list[ActivitySnapshot] = []

    def initialize_redis(self) -> None:
        t = self.config.ticker.lower()
        redis_client.delete(f"{t}_activity_snapshots", f"{t}_minute_logs", f"{t}_rolling_metrics_logs")
        print(f"✅ Redis initialized for {self.config.ticker}.")

    def save_to_redis(self) -> None:
        t = self.config.ticker.lower()
        # Cap lists to prevent memory leaks in redis (e.g. keeping latest 60)
        redis_client.set(f"{t}_activity_snapshots", json.dumps([d.model_dump() for d in self.activity_snapshots[-60:]]))
        redis_client.set(f"{t}_minute_logs", json.dumps([d.model_dump() for d in self.minute_logs[-60:]]))
        redis_client.set(f"{t}_rolling_metrics_logs", json.dumps([d.model_dump() for d in self.rolling_metrics_logs[-60:]]))


def load_configs() -> list[TickerConfig]:
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tickers_config.json')
    if not os.path.exists(config_path):
        print(f"⚠️  Config file not found at {config_path}")
        return []
    with open(config_path, 'r') as f:
        data = json.load(f)
    return [TickerConfig(**item) for item in data]


def format_timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime('%H:%M:%S')

def format_minute(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def calculate_wap(prices: list[float], quantities: list[float]) -> float:
    total_qty = sum(quantities)
    return sum(p * q for p, q in zip(prices, quantities)) / total_qty if total_qty else 0

def normalize_value(current_value: float, percentile_20: float, percentile_80: float) -> float:
    if current_value <= percentile_20:
        return 0.0
    elif current_value >= percentile_80:
        return 1.0
    else:
        return (current_value - percentile_20) / (percentile_80 - percentile_20)


async def analyze_trade_activity(state: TickerState) -> None:
    ticker = state.config.ticker
    trade_url = f"wss://stream.binance.com:9443/ws/{ticker.lower()}@trade"
    current_minute: datetime | None = None
    already_triggered_20s: bool = False

    async with websockets.connect(trade_url) as trade_ws:
        print(f"📡 Running rolling window stream for {ticker.upper()}...")

        while True:
            try:
                data = json.loads(await trade_ws.recv())

                price: float = float(data["p"])
                quantity: float = float(data["q"])
                is_buyer_maker: bool = data["m"]
                event_time: int = data["T"]

                trade_minute: datetime = datetime.fromtimestamp(event_time / 1000).replace(second=0, microsecond=0)

                # Reset per minute
                if current_minute is None:
                    current_minute = trade_minute
                    already_triggered_20s = False

                if trade_minute != current_minute:
                    minute_data: MinuteSummary = generate_minute_data(current_minute, state.rolling_window_trades)
                    state.minute_logs.append(minute_data)
                    # Keep local memory bound
                    if len(state.minute_logs) > 60: state.minute_logs.pop(0)
                        
                    current_minute = trade_minute
                    already_triggered_20s = False

                # ----------------
                # Rolling window logic
                # ----------------
                # Update rolling window
                state.rolling_window_trades.append((event_time, price, quantity))
                cutoff_time: int = event_time - 10000
                state.rolling_window_trades[:] = [t for t in state.rolling_window_trades if t[0] >= cutoff_time]

                # Generate metrics for rolling window on every trade
                rolling_data: ActivitySnapshot = generate_activity_snapshot(event_time, state.rolling_window_trades, state.config)
                state.rolling_metrics_logs.append(rolling_data)
                if len(state.rolling_metrics_logs) > 60: state.rolling_metrics_logs.pop(0)

                # Trigger activity snapshot at 20s mark
                if not already_triggered_20s and 20000 <= (event_time % 60000) <= 21000:
                    activity_snapshot: ActivitySnapshot = generate_activity_snapshot(event_time, state.rolling_window_trades, state.config)
                    state.activity_snapshots.append(activity_snapshot)
                    if len(state.activity_snapshots) > 60: state.activity_snapshots.pop(0)
                        
                    print(f"\n📊 [{ticker.upper()}] Activity Snapshot Triggered @ {activity_snapshot.timestamp}")
                    already_triggered_20s = True

                state.save_to_redis()

            except (websockets.ConnectionClosedError, websockets.ConnectionClosedOK) as e:
                print(f"⚠️ WebSocket disconnected for {ticker}: {e}")
                await asyncio.sleep(2)


def generate_minute_data(current_minute: datetime, trades_window: list[TradeEntry]) -> MinuteSummary:
    prices: list[float] = [t[1] for t in trades_window]
    quantities: list[float] = [t[2] for t in trades_window]
    total_volume: float = sum(quantities)
    return MinuteSummary(
        timestamp=format_minute(current_minute),
        trades=len(trades_window),
        volume=round(total_volume, 3),
        avg_price=round(np.mean(prices) if prices else 0, 5),
    )


def generate_activity_snapshot(event_time: int, trades_window: list[TradeEntry], config: TickerConfig) -> ActivitySnapshot:
    prices: list[float] = [t[1] for t in trades_window]
    quantities: list[float] = [t[2] for t in trades_window]
    total_volume: float = sum(quantities)
    avg_price: float = np.mean(prices) if prices else 0
    std_dev: float = np.std(prices) if prices else 0
    slope: float = prices[-1] - prices[0] if len(prices) > 1 else 0
    wap: float = calculate_wap(prices, quantities)
    trade_count: int = len(trades_window)

    # Activity Quality check
    is_qualified_activity: bool = False
    activity_score: float = 0.0

    if config.min_volume_threshold < total_volume < config.max_volume_threshold:
        if trade_count > config.min_trade_count and config.min_std_dev < std_dev < config.max_std_dev:
            is_qualified_activity = True
            normalized_volume: float = normalize_value(total_volume, config.min_volume_threshold, config.max_volume_threshold)
            normalized_std_dev: float = normalize_value(std_dev, config.min_std_dev, config.max_std_dev)
            normalized_trade_count: float = normalize_value(trade_count, config.min_trade_count, config.max_trade_count)
            activity_score = (normalized_volume + normalized_std_dev + normalized_trade_count) / 3

    return ActivitySnapshot(
        timestamp=format_timestamp(event_time),
        is_qualified_activity=is_qualified_activity,
        activity_score=round(activity_score, 5),
        trades=trade_count,
        volume=round(total_volume, 3),
        avg_price=round(avg_price, 5),
        wap=round(wap, 5),
        std_dev=round(std_dev, 5),
        slope=round(slope, 5),
    )


async def main():
    configs = load_configs()
    if not configs:
        print("❌ No tickers configured. Please ensure tickers_config.json is populated.")
        return

    states = []
    for cfg in configs:
        state = TickerState(cfg)
        state.initialize_redis()
        states.append(state)

    # Run streams concurrently
    tasks = [analyze_trade_activity(state) for state in states]
    print(f"🚀 Starting monitors for {len(tasks)} tickers concurrently...")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
