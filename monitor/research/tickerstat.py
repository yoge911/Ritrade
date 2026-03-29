import asyncio
import websockets
import json
import pandas as pd
import numpy as np
import sys
from datetime import datetime

async def collect_baseline_data(ticker="BTCUSDC", interval=20, total_duration_minutes=60, output_csv=None):
    """
    Collects trade count, total volume, and price std deviation every interval seconds.
    Saves the final data into a CSV file for analysis.
    """
    url = f"wss://stream.binance.com:9443/ws/{ticker.lower()}@trade"
    interval_ms = interval * 1000
    end_time = datetime.now().timestamp() + (total_duration_minutes * 60)

    # Buffers
    price_data = []
    trade_count = 0
    total_volume = 0.0
    current_bucket = None

    # Output records
    collected_data = []

    async with websockets.connect(url) as ws:
        print(f"📡 Collecting baseline data for {ticker.upper()} every {interval} seconds...")

        while datetime.now().timestamp() < end_time:
            msg = await ws.recv()
            data = json.loads(msg)

            price = float(data["p"])
            quantity = float(data["q"])
            trade_event_time = data["T"]

            trade_bucket = (trade_event_time // interval_ms) * interval_ms

            if current_bucket is None:
                current_bucket = trade_bucket

            if trade_bucket == current_bucket:
                price_data.append(price)
                trade_count += 1
                total_volume += quantity
            else:
                std_dev = np.std(price_data) if price_data else 0
                timestamp = datetime.fromtimestamp(current_bucket / 1000).strftime('%Y-%m-%d %H:%M:%S')

                collected_data.append({
                    "timestamp": timestamp,
                    "trade_count": trade_count,
                    "total_volume": total_volume,
                    "std_dev": std_dev
                })

                print(f"✅ Collected: {timestamp} | Trades: {trade_count} | Volume: {round(total_volume, 4)} | StdDev: {round(std_dev, 6)}")

                price_data = [price]
                trade_count = 1
                total_volume = quantity
                current_bucket = trade_bucket

    # Create default output file name if not provided
    if output_csv is None:
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_csv = f"{ticker.lower()}_baseline_{now_str}.csv"

    # Save to CSV
    df = pd.DataFrame(collected_data)
    df.to_csv(output_csv, index=False)
    print(f"\n📂 Baseline data collection complete! Saved to {output_csv}")

# Main runner
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python collect_baseline_data.py <TICKER>")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    asyncio.run(collect_baseline_data(
        ticker=ticker,
        interval=20,                # 10s collection windows
        total_duration_minutes=60,  # 1-hour run
        output_csv=None             # auto-generate filename
    ))
