import asyncio
import websockets
import json
import numpy as np
import pandas as pd
from collections import deque
from utility.logger.log import log
from tabulate import tabulate
from datetime import datetime

async def analyze_trade_activity(ticker="BTCUSDT", interval=10):
    """
    Continuously listens to Binance @trade stream and calculates summary statistics
    every `interval` seconds using Binance's event time for precise window alignment.
    """
    url = f"wss://stream.binance.com:9443/ws/{ticker.lower()}@trade"

    price_data = []
    buy_volume = 0.0
    sell_volume = 0.0
    trade_count = 0
    current_bucket = None
    interval_ms = interval * 1000



    async with websockets.connect(url) as ws:
        print(f"📡 Running aligned analysis for {ticker.upper()} every {interval} seconds...")

        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            price = float(data["p"])
            quantity = float(data["q"])
            is_buyer_maker = data["m"]
            trade_event_time = data["T"] 

            # Determine the bucket this trade belongs to
            trade_bucket = (trade_event_time // interval_ms) * interval_ms

            # Initialize first bucket
            if current_bucket is None:
                current_bucket = trade_bucket

            if trade_bucket == current_bucket:
                price_data.append(price)
                trade_count += 1

                # Aggregate buy/sell volumes based on taker side
                if is_buyer_maker:
                    sell_volume += quantity  # Seller was taker
                else:
                    buy_volume += quantity  # Buyer was taker

            else:

               
                # Volume Authenticity Filter
                authentic_volume = False
                min_total_volume = 10   # example threshold
                min_trade_count = 15    # example threshold
                total_volume = buy_volume + sell_volume
                timestamp = datetime.fromtimestamp(current_bucket / 1000).strftime('%H:%M:%S')

                if total_volume >= min_total_volume and trade_count >= min_trade_count:
                    authentic_volume = True
                else:
                    authentic_volume = False
                    print(f"\n⚠️ SKIP @ {timestamp} — Weak/Fake Volume: Volume={total_volume:.2f}, Trades={trade_count}")


                # Calculate stats for the completed bucket
                slope = price_data[-1] - price_data[0] if len(price_data) > 1 else 0
                std_dev = np.std(price_data)
                price_range = max(price_data) - min(price_data) if price_data else 0
                avg_price = sum(price_data) / len(price_data) if price_data else 0
               

               # Normalize std_dev into a 1–10 volatility score for readability
                min_std, max_std = 0.001, 0.020  # Narrower, more realistic for crypto micro analysis
                normalized = (std_dev - min_std) / (max_std - min_std)
                normalized = max(0, min(normalized, 1))  # Clamp after normalization
                volatility_score = round(1 + normalized * 9, 2)



                print(f"\n📊 Snapshot @ {timestamp}")
                print(f"  ▸ Authentic       : {authentic_volume}")
                print(f"  ▸ Volume            : {round(total_volume, 3)}, Buy : {round(buy_volume, 3)}, Sell : {round(sell_volume, 3)}")
                print(f"  ▸ Average Price     : {round(avg_price, 5)}")
                print(f"  ▸ Price Slope       : {round(slope, 5)}")
                print(f"  ▸ Price Std Dev     : {round(std_dev, 5)}")
                print(f"  ▸ Volatility Score  : {volatility_score} / 10")
                print(f"  ▸ Price Range       : {round(price_range, 5)}")
                print(f"  ▸ Trade Frequency   : {round(trade_count / interval, 2)} trades/sec")

                # Reset for the new bucket
                price_data = [price]
                trade_count = 1
                buy_volume = 0.0
                sell_volume = 0.0
                current_bucket = trade_bucket


# For direct run and testing
if __name__ == "__main__":
    result = asyncio.run(analyze_trade_activity("BTCUSDT", 5))
    print(result)   
