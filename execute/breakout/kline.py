from datetime import datetime
import json
import websockets
import redis

# Example response
# uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_{self.interval}"
# {
#   "e": "kline",     // Event type
#   "E": 1638747660000,   // Event time
#   "s": "BTCUSDT",    // Symbol
#   "k": {
#     "t": 1638747660000, // Kline start time
#     "T": 1638747719999, // Kline close time
#     "s": "BTCUSDT",  // Symbol
#     "i": "1m",      // Interval
#     "f": 100,       // First trade ID
#     "L": 200,       // Last trade ID
#     "o": "0.0010",  // Open price
#     "c": "0.0020",  // Close price
#     "h": "0.0025",  // High price
#     "l": "0.0015",  // Low price
#     "v": "1000",    // Base asset volume
#     "n": 100,       // Number of trades
#     "x": false,     // Is this kline closed?
#     "q": "1.0000",  // Quote asset volume
#     "V": "500",     // Taker buy base asset volume
#     "Q": "0.500",   // Taker buy quote asset volume
#     "B": "123456"   // Ignore
#   }
# }

class Kline:
    # Constructor
    def __init__(self, symbol, interval, candle_buffer_size=-1, on_candle=None):
        self.symbol = symbol
        self.interval = interval
        self.candle_buffer_size = candle_buffer_size
        self.candle_buffer = []
        self.on_candle = on_candle

        # Redis connection
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

    # Method to start the listener
    async def listen(self):
        uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_{self.interval}"
        async with websockets.connect(uri) as websocket:
            while True:
                data = await websocket.recv()
                json_data = json.loads(data)
                kline = json_data['k']

                active_data = {
                    'event_time': json_data['E'],
                    'symbol': json_data['s'],
                    'live_price' : float(kline['c']),
                    'interval': kline['i'],
                }

                # Publish active data to Redis
                self.redis_client.publish(f"{self.symbol}_event_channel", json.dumps(active_data)) 
                
                if kline['x']:  # candle closed
                    high = float(kline['h'])
                    low = float(kline['l'])
                    open = float(kline['o'])  
                    close = float(kline['c'])
                    close_time = kline['T']                    
                
                    # Add candle to buffer
                    if self.candle_buffer_size < 0 :                        
                        self.candle_buffer.append({'high': high, 'low': low, 'open': open,  'close': close, 'close_time': close_time})
                        
                        # Keep only N last candles (Only pop if buffer_size >= 0)
                        if self.candle_buffer_size >= 0 and len(self.candle_buffer) > self.candle_buffer_size:
                            self.candle_buffer.pop(0)

                        # Call the callback function if provided
                        if self.on_candle:
                           self.on_candle(self.candle_buffer)        








