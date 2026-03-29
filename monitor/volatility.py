import requests
import pandas as pd
import time
import math
import redis
import json

# Configuration
TOP_N = 5
CANDLE_INTERVAL = '1m'
LOOKBACK_CANDLES = 15
BASE_URL = "https://api.binance.com"

# Redis connection
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Predefined top market cap USDT tickers
TOP_TICKERS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT',
    'LINKUSDT', 'TONUSDT', 'TRXUSDT', 'ICPUSDT', 'LTCUSDT',
    'ETCUSDT', 'XMRUSDT', 'FILUSDT', 'INJUSDT', 'UNIUSDT'
]


def fetch_kline_data(symbol, interval, limit):
    url = f"{BASE_URL}/api/v3/klines"
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    return None


def analyze_predefined_tickers():
    """
    Analyzes pre-defined tickers and ranks them based on a custom volatility score.
    
    Scoring Logic:
    score = (abs(price_change) * 2.5) + log10(total_quote_volume + 1) - (avg_spread * 1.5) - volume_penalty
    
    - Rewards high absolute price movement (strong momentum).
    - Rewards high trading volume logarithmically (good liquidity).
    - Penalizes assets with less than $500k volume in the lookback window.
    - Penalizes wide average spreads to avoid choppy, erratic wicks.
    """
    results = []

    for i, symbol in enumerate(TOP_TICKERS):
        # print(f"[{i+1}/{len(TOP_TICKERS)}] Checking {symbol}...")

        klines = fetch_kline_data(symbol, CANDLE_INTERVAL, LOOKBACK_CANDLES)
        if not klines:
            continue

        df = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'])

        df = df.astype({
            'open': float, 'high': float, 'low': float,
            'close': float, 'volume': float, 'quote_asset_volume': float
        })

        price_change = (df['close'].iloc[-1] - df['open'].iloc[0]) / df['open'].iloc[0] * 100
        total_quote_volume = df['quote_asset_volume'].sum()
        avg_spread = (df['high'] - df['low']).mean() / df['close'].mean() * 100

        last_price = df['close'].iloc[-1]
        volume_penalty = 5 if total_quote_volume < 500000 else 0
        score = (abs(price_change) * 2.5) + math.log10(total_quote_volume + 1) - (avg_spread * 1.5) - volume_penalty

        results.append({
            'symbol': symbol,
            'last_price': round(last_price, 4),
            'price_change_pct': round(price_change, 2),
            'quote_volume': round(total_quote_volume, 2),
            'avg_spread_pct': round(avg_spread, 4),
            'score': round(score, 2)
        })

    df_result = pd.DataFrame(results)
    df_result.sort_values(by='score', ascending=False, inplace=True)
    print("\n📊 Top Market Cap Volatile Tickers:")
    print(df_result.head(TOP_N))

    top_symbols = df_result.head(TOP_N)['symbol'].tolist()
    
    # Save to Redis
    redis_client.set("top_volatile_tickers", json.dumps(top_symbols))
    print(f"🔥 Saved top {TOP_N} volatile tickers to Redis ('top_volatile_tickers')")

    # Save to text file as a backup
    with open("volatile_tickers.txt", "w") as f:
        for symbol in top_symbols:
            f.write(symbol + "\n")


if __name__ == "__main__":
    analyze_predefined_tickers()
