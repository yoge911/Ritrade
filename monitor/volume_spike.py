import asyncio
import websockets
import json
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from collections import deque
from core_utils.logger.log import log

import subprocess

# Configuration
TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
WINDOW_SIZE = 10
SPIKE_THRESHOLD = 2
BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream?streams="

"""
Volume Spike Detection Script
This script connects to the Binance WebSocket API and listens for volume data
for specified tickers. It calculates the average volume over a defined window size
and detects volume spikes based on a specified threshold. If a spike is detected,
a notification sound is played.

Strategy: If the current volume > 2 * average volume over the last 10 candles, 
this indicator is used to assess a possible Entry point.

"""

# Initialize volume history per ticker
volume_history = {ticker.lower(): deque(maxlen=WINDOW_SIZE) for ticker in TICKERS}
subprocess.Popen(["afplay", "core_utils/tones/notification-beep-229154.mp3"])
log("Volume spike detection script started.")

async def handle_stream():
    streams = "/".join([f"{ticker.lower()}@kline_1m" for ticker in TICKERS])
    url = BINANCE_WS_BASE + streams

    async with websockets.connect(url) as ws:
        log("📡 Listening to volume data...")
        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            kline = data.get("data", {}).get("k")
            
            if not kline or not kline["x"]:
                continue  # Skip if candle not closed

            symbol = kline["s"].lower()
            volume = float(kline["v"])
            volume_history[symbol].append(volume)
            price = float(kline["c"])
           

            log(f"📊 {symbol.upper()} - Volume: {volume:.2f}")

            if len(volume_history[symbol]) == WINDOW_SIZE:                
                avg_volume = sum(volume_history[symbol]) / WINDOW_SIZE

                if volume > avg_volume * SPIKE_THRESHOLD:
                    subprocess.Popen(["afplay", "core_utils/tones/notification-beep-229154.mp3"])
                    log(f"🚨 Volume spike on {symbol.upper()}! Volume: {volume:.2f}, Avg: {avg_volume:.2f}, Price : {price}")
                    

async def main():
    try:
        await handle_stream()
    except KeyboardInterrupt:
        log("🛑 Script stopped by user.")



if __name__ == "__main__":
    asyncio.run(main())