import asyncio
import websockets
import json
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from collections import deque
from core_utils.logger.log import log

strategy_trigger_min = 20
ticker = "BTCUSDT"

async def candle_average_price(ticker):
    """
    Collects trade prices in real-time from Binance WebSocket
    and calculates the average price at the 20th second of each minute.
    """
    url = f"wss://stream.binance.com:9443/ws/{ticker.lower()}@trade"
    price_buffer = deque()
    current_minute = None

    async with websockets.connect(url) as ws:
        print(f"📡 Listening to {ticker.upper()} trade data...")

        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            price = float(data['p'])  # trade price
            event_time = datetime.fromtimestamp(data['T'] / 1000)

            # Track minute and second
            minute = event_time.replace(second=0, microsecond=0)
            second = event_time.second

            # Reset buffer on a new minute
            if current_minute is None or minute != current_minute:
                current_minute = minute
                price_buffer.clear()

            # Store trade price
            price_buffer.append(price)

            if second == 20 or second == 30 or second == 40 or second == 50:
                if price_buffer:
                    avg_price = sum(price_buffer) / len(price_buffer)
                    print(f"[{event_time.strftime('%H:%M:%S')}] 🧠 Avg Price at 20s for {ticker.upper()}: {avg_price:.4f}")
                else:
                    print(f"[{event_time.strftime('%H:%M:%S')}] ⚠️ No trades collected yet.")



asyncio.run(candle_average_price(ticker))
