import asyncio
import websockets
import json
import numpy as np
import redis
from datetime import datetime
from pydantic import BaseModel

# set ticker configuration
ticker: str = "BTCUSDC"
min_auth_volume: float = 0.1003
max_auth_volume: float = 1.1916
min_trade_count: int = 24
max_trade_count: int = 295
min_std_dev: float = 0.004749
max_std_dev: float = 4.0196

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Type alias: (timestamp_ms, price, quantity)
TradeEntry = tuple[int, float, float]


class TrapData(BaseModel):
    timestamp: str
    authentic_volume: bool
    dynamic_factor: float
    trades: int
    volume: float
    avg_price: float
    wap: float
    std_dev: float
    slope: float


class MinuteData(BaseModel):
    timestamp: str
    trades: int
    volume: float
    avg_price: float


# Data logs
rolling_window_trades: list[TradeEntry] = []
trap_logs: list[TrapData] = []
minute_logs: list[MinuteData] = []
rolling_metrics_logs: list[TrapData] = []


def initialize_redis() -> None:
    redis_client.delete("trap_logs", "trap_logs")
    redis_client.delete("minute_logs", "minute_logs")
    redis_client.delete("rolling_metrics_logs", "rolling_metrics_logs")
    print("✅ Redis initialized.")

def save_to_redis() -> None:
    redis_client.set("trap_logs", json.dumps([d.model_dump() for d in trap_logs]))
    redis_client.set("minute_logs", json.dumps([d.model_dump() for d in minute_logs]))
    redis_client.set("rolling_metrics_logs", json.dumps([d.model_dump() for d in rolling_metrics_logs]))

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

async def analyze_trade_activity(ticker: str = "BTCUSDC") -> None:
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
                    minute_data: MinuteData = generate_minute_data(current_minute, rolling_window_trades)
                    log_minute(minute_data)
                    current_minute = trade_minute
                    already_triggered_20s = False

                # ----------------
                # Rolling window logic
                # ----------------
                # Update rolling window
                rolling_window_trades.append((event_time, price, quantity))
                cutoff_time: int = event_time - 10_000
                rolling_window_trades[:] = [t for t in rolling_window_trades if t[0] >= cutoff_time]

                # 🆕 Generate metrics for rolling window on every trade
                rolling_data: TrapData = generate_trap_data(event_time, rolling_window_trades)
                log_rolling_metric(rolling_data)

                # Trigger trap at 20s mark (keep this logic as is)
                if not already_triggered_20s and 20_000 <= (event_time % 60000) <= 21_000:
                    trap_data: TrapData = generate_trap_data(event_time, rolling_window_trades)
                    log_trap(trap_data)
                    already_triggered_20s = True


                save_to_redis()

            except (websockets.ConnectionClosedError, websockets.ConnectionClosedOK) as e:
                print(f"⚠️ WebSocket disconnected: {e}")
                await asyncio.sleep(2)

def generate_minute_data(current_minute: datetime, trades_window: list[TradeEntry]) -> MinuteData:
    prices: list[float] = [t[1] for t in trades_window]
    quantities: list[float] = [t[2] for t in trades_window]
    total_volume: float = sum(quantities)
    return MinuteData(
        timestamp=format_minute(current_minute),
        trades=len(trades_window),
        volume=round(total_volume, 3),
        avg_price=round(np.mean(prices) if prices else 0, 5),
    )

def generate_trap_data(event_time: int, trades_window: list[TradeEntry]) -> TrapData:
    prices: list[float] = [t[1] for t in trades_window]
    quantities: list[float] = [t[2] for t in trades_window]
    total_volume: float = sum(quantities)
    avg_price: float = np.mean(prices) if prices else 0
    std_dev: float = np.std(prices) if prices else 0
    slope: float = prices[-1] - prices[0] if len(prices) > 1 else 0
    wap: float = calculate_wap(prices, quantities)
    trade_count: int = len(trades_window)

    # Authenticity check
    authentic_volume: bool = False
    dynamic_factor: float = 0.0

    if min_auth_volume < total_volume < max_auth_volume:
        if trade_count > min_trade_count and min_std_dev < std_dev < max_std_dev:
            authentic_volume = True
            normalized_volume: float = normalize_value(total_volume, min_auth_volume, max_auth_volume)
            normalized_std_dev: float = normalize_value(std_dev, min_std_dev, max_std_dev)
            normalized_trade_count: float = normalize_value(trade_count, min_trade_count, max_trade_count)
            dynamic_factor = (normalized_volume + normalized_std_dev + normalized_trade_count) / 3

    return TrapData(
        timestamp=format_timestamp(event_time),
        authentic_volume=authentic_volume,
        dynamic_factor=round(dynamic_factor, 5),
        trades=trade_count,
        volume=round(total_volume, 3),
        avg_price=round(avg_price, 5),
        wap=round(wap, 5),
        std_dev=round(std_dev, 5),
        slope=round(slope, 5),
    )

def log_minute(minute_data: MinuteData) -> None:
    minute_logs.append(minute_data)

def log_trap(trap_data: TrapData) -> None:
    trap_logs.append(trap_data)
    print(f"\n📊 Trap Triggered @ {trap_data.timestamp}")

def log_rolling_metric(data: TrapData) -> None:
    rolling_metrics_logs.append(data)
    # optional: print or limit list size
    if len(rolling_metrics_logs) % 50 == 0:
        print(f"📈 Logged {len(rolling_metrics_logs)} rolling snapshots.")


if __name__ == "__main__":
    initialize_redis()
    asyncio.run(analyze_trade_activity(ticker=ticker))
