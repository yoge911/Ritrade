import asyncio
import websockets
import json
import numpy as np
import redis
from datetime import datetime
from pydantic import BaseModel

# set ticker configuration
ticker: str = "BTCUSDC"
bucket_interval: int = 10  # seconds
min_auth_volume: float = 0.1003
max_auth_volume: float = 1.1916
min_trade_count: int = 24
max_trade_count: int = 295
min_std_dev: float = 0.004749
max_std_dev: float = 4.0196

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)


class TrapData(BaseModel):
    timestamp: str
    av_20: float
    wap_20: float
    std_dev: float
    slope: float
    buy_volume: float
    sell_volume: float
    total_volume: float


class MinuteData(BaseModel):
    timestamp: str
    trades: int
    volume: float
    buy_volume: float
    sell_volume: float


class BucketData(BaseModel):
    timestamp: str
    authentic_volume: bool
    dynamic_factor: float
    trades: int
    volume: float
    avg_price: float
    wap: float
    std_dev: float
    slope: float


# Data logs
bucket_logs: list[BucketData] = []
trap_logs: list[TrapData] = []
minute_logs: list[MinuteData] = []


def initialize_redis() -> None:
    redis_client.delete("bucket_logs", "trap_logs", "minute_logs")
    print("✅ Redis initialized.")

def save_to_redis() -> None:
    redis_client.set("bucket_logs", json.dumps([d.model_dump() for d in bucket_logs]))
    redis_client.set("trap_logs", json.dumps([d.model_dump() for d in trap_logs]))
    redis_client.set("minute_logs", json.dumps([d.model_dump() for d in minute_logs]))

def format_timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime('%H:%M:%S')

def format_minute(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def calculate_wap(prices: list[float], quantities: list[float]) -> float:
    total_qty = sum(quantities)
    return sum(p * q for p, q in zip(prices, quantities)) / total_qty if total_qty else 0

def reset_master_buffers() -> tuple[list[float], list[float], float, float, int]:
    return [], [], 0.0, 0.0, 0

def reset_bucket_buffers() -> tuple[list[float], list[float], float, float, int]:
    return [], [], 0.0, 0.0, 0

def normalize_value(current_value: float, percentile_20: float, percentile_80: float) -> float:
    """
    Normalize the current value between 0 and 1
    based on the given 20th and 80th percentile boundaries.
    """

    # Clamp if necessary
    if current_value <= percentile_20:
        return 0.0
    elif current_value >= percentile_80:
        return 1.0
    else:
        return (current_value - percentile_20) / (percentile_80 - percentile_20)


async def analyze_trade_activity(ticker: str = "BTCUSDC", bucket_interval: int = 10) -> None:

    trade_url = f"wss://stream.binance.com:9443/ws/{ticker.lower()}@trade"
    # kline_url = f"wss://stream.binance.com:9443/ws/{ticker.lower()}@kline_1m"
    bucket_interval_ms: int = bucket_interval * 1000

    # Buffers
    master_price_data, master_quantity_data, master_buy_volume, master_sell_volume, master_trade_count = reset_master_buffers()
    bucket_price_data, bucket_quantity_data, bucket_buy_volume, bucket_sell_volume, bucket_trade_count = reset_bucket_buffers()

    current_minute: datetime | None = None
    current_bucket: int | None = None
    last_closed_candle: dict | None = None
    already_triggered_20s: bool = False

    # async with websockets.connect(trade_url) as trade_ws, websockets.connect(kline_url) as kline_ws:
    async with websockets.connect(trade_url) as trade_ws:
        print(f"📡 Running dual stream for {ticker.upper()} with {bucket_interval}s buckets...")

        async def handle_trade() -> None:
            nonlocal master_price_data, master_quantity_data, master_buy_volume, master_sell_volume, master_trade_count
            nonlocal bucket_price_data, bucket_quantity_data, bucket_buy_volume, bucket_sell_volume, bucket_trade_count
            nonlocal current_minute, current_bucket, already_triggered_20s, last_closed_candle

            while True:
                try:
                    data = json.loads(await trade_ws.recv())

                    price: float = float(data["p"])
                    quantity: float = float(data["q"])
                    is_buyer_maker: bool = data["m"]
                    event_time: int = data["T"]

                    trade_minute: datetime = datetime.fromtimestamp(event_time / 1000).replace(second=0, microsecond=0)
                    trade_bucket: int = (event_time // bucket_interval_ms) * bucket_interval_ms

                    if current_minute is None:
                        current_minute, current_bucket = trade_minute, trade_bucket

                    if trade_minute != current_minute:
                        minute_data: MinuteData = generate_minute_data(current_minute, master_trade_count, master_buy_volume, master_sell_volume)
                        log_minute(minute_data)
                        master_price_data, master_quantity_data, master_buy_volume, master_sell_volume, master_trade_count = reset_master_buffers()
                        current_minute, current_bucket, already_triggered_20s = trade_minute, trade_bucket, False

                    if trade_bucket != current_bucket:
                        bucket_data: BucketData = generate_bucket_data(current_bucket, bucket_trade_count, bucket_price_data, bucket_quantity_data, bucket_buy_volume, bucket_sell_volume)
                        log_bucket(bucket_data)
                        bucket_price_data, bucket_quantity_data, bucket_buy_volume, bucket_sell_volume, bucket_trade_count = reset_bucket_buffers()
                        current_bucket = trade_bucket

                    master_price_data.append(price)
                    master_quantity_data.append(quantity)
                    master_trade_count += 1

                    bucket_price_data.append(price)
                    bucket_quantity_data.append(quantity)
                    bucket_trade_count += 1

                    if is_buyer_maker:
                        master_sell_volume += quantity
                        bucket_sell_volume += quantity
                    else:
                        master_buy_volume += quantity
                        bucket_buy_volume += quantity

                    if not already_triggered_20s and 20_000 <= (event_time % 60000) <= 21_000:
                        trap_data: TrapData = generate_trap_data(event_time, master_price_data, master_quantity_data, master_buy_volume, master_sell_volume)
                        log_trap(trap_data)
                        already_triggered_20s = True

                    save_to_redis()

                except (websockets.ConnectionClosedError, websockets.ConnectionClosedOK) as e:
                    print(f"⚠️ Trade WebSocket disconnected: {e}")
                    await asyncio.sleep(2)

        async def handle_kline() -> None:
            nonlocal last_closed_candle
            while True:
                try:
                    data = json.loads(await kline_ws.recv())
                    kline = data.get("k")
                    if kline and kline["x"]:
                        last_closed_candle = {
                            "open": float(kline["o"]),
                            "high": float(kline["h"]),
                            "low": float(kline["l"]),
                            "close": float(kline["c"]),
                            "volume": float(kline["v"])
                        }
                except (websockets.ConnectionClosedError, websockets.ConnectionClosedOK) as e:
                    print(f"⚠️ Kline WebSocket disconnected: {e}")
                    await asyncio.sleep(2)

        # await asyncio.gather(handle_trade(), handle_kline())
        await asyncio.gather(handle_trade())

def generate_minute_data(current_minute: datetime, trade_count: int, buy_volume: float, sell_volume: float) -> MinuteData:
    return MinuteData(
        timestamp=format_minute(current_minute),
        trades=trade_count,
        volume=round(buy_volume + sell_volume, 3),
        buy_volume=round(buy_volume, 3),
        sell_volume=round(sell_volume, 3),
    )

def generate_bucket_data(current_bucket: int, trade_count: int, price_data: list[float], quantity_data: list[float], buy_volume: float, sell_volume: float) -> BucketData:
    total_volume: float = buy_volume + sell_volume
    avg_price: float = np.mean(price_data) if price_data else 0
    std_dev: float = np.std(price_data) if price_data else 0
    slope: float = price_data[-1] - price_data[0] if len(price_data) > 1 else 0
    wap: float = calculate_wap(price_data, quantity_data)

    authentic_volume: bool = False
    dynamic_factor: float = 0.0
    if total_volume > min_auth_volume and total_volume < max_auth_volume:
        if trade_count > min_trade_count and std_dev > min_std_dev and std_dev < max_std_dev:
            authentic_volume = True
            normalized_volume: float = normalize_value(total_volume, min_auth_volume, max_auth_volume)
            normalized_std_dev: float = normalize_value(std_dev, min_std_dev, max_std_dev)
            normalized_trade_count: float = normalize_value(trade_count, min_trade_count, max_trade_count)
            dynamic_factor = (normalized_volume + normalized_std_dev + normalized_trade_count) / 3

    return BucketData(
        timestamp=format_timestamp(current_bucket),
        authentic_volume=authentic_volume,
        dynamic_factor=round(dynamic_factor, 5),
        trades=trade_count,
        volume=round(total_volume, 3),
        avg_price=round(avg_price, 5),
        wap=round(wap, 5),
        std_dev=round(std_dev, 5),
        slope=round(slope, 5),
    )

def generate_trap_data(event_time: int, price_data: list[float], quantity_data: list[float], master_buy_volume: float, master_sell_volume: float) -> TrapData:
    avg_price: float = np.mean(price_data) if price_data else 0
    wap: float = calculate_wap(price_data, quantity_data)
    std_dev: float = np.std(price_data) if price_data else 0
    slope: float = price_data[-1] - price_data[0] if len(price_data) > 1 else 0
    total_volume: float = master_buy_volume + master_sell_volume

    return TrapData(
        timestamp=format_timestamp(event_time),
        av_20=round(avg_price, 5),
        wap_20=round(wap, 5),
        std_dev=round(std_dev, 5),
        slope=round(slope, 5),
        buy_volume=round(master_buy_volume, 5),
        sell_volume=round(master_sell_volume, 5),
        total_volume=round(total_volume, 5),
    )

def log_minute(minute_data: MinuteData) -> None:
    minute_logs.append(minute_data)

def log_bucket(bucket_data: BucketData) -> None:
    bucket_logs.append(bucket_data)

def log_trap(trap_data: TrapData) -> None:
    trap_logs.append(trap_data)
    print(f"\n📊 Trap Triggered @ {trap_data.timestamp}")

if __name__ == "__main__":
    # Initialize Redis
    initialize_redis()
    asyncio.run(analyze_trade_activity(ticker=ticker, bucket_interval=bucket_interval))
