import asyncio
import websockets
import json

async def kline_listener():
    uri = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
    
    candle_buffer = []  # stores last N candles
    
    async with websockets.connect(uri) as websocket:
        while True:
            data = await websocket.recv()
            json_data = json.loads(data)
            kline = json_data['k']
            
            if kline['x']:  # candle closed
                high = float(kline['h'])
                low = float(kline['l'])
                close = float(kline['c'])
                
                # add candle to buffer
                candle_buffer.append({'high': high, 'low': low, 'close': close})
                
                # keep only last 20 candles
                if len(candle_buffer) > 20:
                    candle_buffer.pop(0)
                
                # calculate range
                highs = [c['high'] for c in candle_buffer]
                lows = [c['low'] for c in candle_buffer]
                recent_high = max(highs)
                recent_low = min(lows)
                
                print(f"Recent range: {recent_low} - {recent_high}")
                
                # check for breakout
                if close > recent_high:
                    print(f"🚀 Breakout UP at {close}")
                    # place_buy_order()
                elif close < recent_low:
                    print(f"🔻 Breakout DOWN at {close}")
                    # place_sell_order()

asyncio.run(kline_listener())
