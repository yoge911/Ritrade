import asyncio
import json
from execute.breakout.kline import Kline
import redis
from execute.breakout.strategy import volatility_breakout
from execute.trade.trade import Trade


# Configuration
ticker = "solusdc"
interval = "1m"
strategy = "volatility_breakout"

# Trade  configuration
account_balance = 10000
entry_price=174.13
quantity=1666.667
risk_percent, reward_percent = 1, 2
position_type = 'long'  # 'long' or 'short'


# data logs
breakout_logs = []

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)



def initialize_redis():
    redis_client.flushdb()
    print("✅ Redis initialized.")

def save_to_redis():
    redis_client.set("breakout_logs", json.dumps(breakout_logs))

def start_trade():
    trade = Trade(
        ticker=ticker,
        entry_price=entry_price,
        account_balance=account_balance,
        quantity=quantity,
        position_type=position_type,
        risk_percent=risk_percent,
        reward_percent=reward_percent
    )
    return trade

# Function to handle incoming candle data
def handle_listener(candle_data):
    
    if strategy == "volatility_breakout":
        volatility_breakout(candle_data, breakout_logs)
        save_to_redis()
        print(breakout_logs)   

    
    # actively check trade situation
    # provides expected stop loss and take profit targets 


# Intiate candle stream
async def main():
    initialize_redis()
    trade = start_trade()
    kline_listener = Kline(symbol=ticker, interval="1m", candle_buffer_size=-1, on_candle=handle_listener)
    await kline_listener.listen()

if __name__ == "__main__":
    asyncio.run(main())

#{'position': 'short', 'entry_price': 1800, 'Zone': 'Profit', 'current_price': 1791.91, 'SL': 0, 'TP': 8.09, 'Stop Price': 1950.0, 'Target Price': 1200.0}
#{'position': 'long', 'entry_price': 1800, 'Zone': 'Loss', 'current_price': 1791.07, 'SL': -8.93, 'TP': 0, 'Stop Price': 1650.0, 'Target Price': 2400.0}
#{'position': 'long', 'entry_price': 1200, 'Zone': 'Profit', 'current_price': 1791.41, 'SL': 0, 'TP': 591.41, 'Stop Price': 1050.0, 'Target Price': 1800.0}
#{'position': 'short', 'entry_price': 1200, 'Zone': 'Loss', 'current_price': 1791.79, 'SL': -591.79, 'TP': 0, 'Stop Price': 1350.0, 'Target Price': 600.0}