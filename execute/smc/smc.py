import asyncio
import websockets
import json
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from datetime import datetime
import matplotlib.dates as mdates


# Parameters
symbol = 'btcusdt'
interval = '1m'
window_size = 100
candles = []
df = pd.DataFrame()

socket_url = f"wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}"

# Matplotlib setup
fig, ax = plt.subplots()
line, = ax.plot([], [], label='Close Price')
scatter = ax.scatter([], [], color='green', label='Continuation Signal')
ax.set_title(f'{symbol.upper()} - {interval.upper()} RIMC Detection')
ax.set_xlabel('Time')
ax.set_ylabel('Price')
ax.legend()
plt.xticks(rotation=45)

def detect_smc_signals():
    global df
    if len(df) < 30:
        return

    df['range_high'] = df['High'].rolling(window=10).max()
    df['range_low'] = df['Low'].rolling(window=10).min()
    df['range_width'] = df['range_high'] - df['range_low']
    df['threshold'] = df['Close'].rolling(window=20).mean() * 0.01
    df.dropna(inplace=True)

    df['in_range'] = df['range_width'] < df['threshold']
    df['initiation'] = (df['Close'] > df['range_high'].shift(1)) & df['in_range'].shift(1)
    df['mitigation'] = df['Low'] < df['range_high'].shift(5)
    df['continuation'] = (df['Close'] > df['Close'].shift(1)) & df['mitigation'].shift(1)

    latest = df.iloc[-1]
    if latest['continuation']:
        print(f"[{latest['timestamp']}] 🟢 CONTINUATION signal at {latest['Close']}")

def update_plot(frame):
    if df.empty or 'timestamp' not in df.columns:
        return line, scatter

    # Convert timestamps to matplotlib date format
    times = mdates.date2num(df['timestamp'])

    # Update the line plot
    line.set_data(times, df['Close'])

    # Update scatter for continuation signals
    entry_signals = df[df['continuation']]
    if not entry_signals.empty:
        signal_times = mdates.date2num(entry_signals['timestamp'])
        scatter.set_offsets(list(zip(signal_times, entry_signals['Close'])))
    else:
        scatter.set_offsets([])  # Clear scatter if no signals

    # Adjust x and y limits
    ax.set_xlim(times.min(), times.max())
    ax.set_ylim(df['Close'].min() * 0.98, df['Close'].max() * 1.02)

    # Format the x-axis with readable time
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    fig.autofmt_xdate()

    return line, scatter



async def listen():
    global df
    async with websockets.connect(socket_url) as websocket:
        async for message in websocket:
            data = json.loads(message)
            kline = data['k']
            candle = {
                'timestamp': pd.to_datetime(kline['t'], unit='ms'),
                'Open': float(kline['o']),
                'High': float(kline['h']),
                'Low': float(kline['l']),
                'Close': float(kline['c']),
                'Volume': float(kline['v']),
                'is_closed': kline['x']
            }
            print (f"Received candle: {candle}")
            if candle['is_closed']:
                candles.append(candle)
                if len(candles) > window_size:
                    candles.pop(0)
                df = pd.DataFrame(candles)
                detect_smc_signals()

def run():
    ani = animation.FuncAnimation(fig, update_plot, interval=1000)
    loop = asyncio.get_event_loop()
    loop.create_task(listen())
    plt.tight_layout()
    plt.show()

# Run the event loop and plotting together
if __name__ == '__main__':
    run()
