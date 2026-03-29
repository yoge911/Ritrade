import asyncio
import json
import redis
from execute.models.trade_config import TradeConfig
from execute.services.kline import Kline
from execute.services.trade import Trade
from execute.breakout.strategy import volatility_breakout


config = TradeConfig(
    ticker='solusdc',
    interval='1m',
    strategy='volatility_breakout',
    account_balance=10000,
    entry_price=174.13,
    quantity=1666.667,
    risk_percent=1,
    reward_percent=2,
    position_type='long',
)

# data logs
breakout_logs = []

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)


def initialize_redis():
    redis_client.flushdb()
    print("✅ Redis initialized.")

def save_to_redis():
    redis_client.set("breakout_logs", json.dumps(breakout_logs))

def start_trade() -> Trade:
    return Trade(
        ticker=config.ticker,
        entry_price=config.entry_price,
        account_balance=config.account_balance,
        quantity=config.quantity,
        position_type=config.position_type,
        risk_percent=config.risk_percent,
        reward_percent=config.reward_percent,
    )

def handle_listener(candle_data: list[dict]) -> None:
    if config.strategy == "volatility_breakout":
        volatility_breakout(candle_data, breakout_logs)
        save_to_redis()
        print(breakout_logs)


async def main():
    initialize_redis()
    start_trade()
    kline_listener = Kline(symbol=config.ticker, interval=config.interval, candle_buffer_size=-1, on_candle=handle_listener)
    await kline_listener.listen()

if __name__ == "__main__":
    asyncio.run(main())