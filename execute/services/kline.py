from typing import Callable, Optional
import json
import websockets
import redis


# Example WebSocket message from Binance kline stream:
# uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_{self.interval}"
# {
#   "e": "kline",               // Event type
#   "E": 1638747660000,         // Event time
#   "s": "BTCUSDT",             // Symbol
#   "k": {
#     "t": 1638747660000,       // Kline start time
#     "T": 1638747719999,       // Kline close time
#     "s": "BTCUSDT",           // Symbol
#     "i": "1m",                // Interval
#     "f": 100,                 // First trade ID
#     "L": 200,                 // Last trade ID
#     "o": "0.0010",            // Open price
#     "c": "0.0020",            // Close price
#     "h": "0.0025",            // High price
#     "l": "0.0015",            // Low price
#     "v": "1000",              // Base asset volume
#     "n": 100,                 // Number of trades
#     "x": false,               // Is this kline closed?
#     "q": "1.0000",            // Quote asset volume
#     "V": "500",               // Taker buy base asset volume
#     "Q": "0.500",             // Taker buy quote asset volume
#     "B": "123456"             // Ignore
#   }
# }


class Kline:
    """
    Connects to the Binance WebSocket kline stream for a given symbol/interval.

    On every tick:
      - Publishes live price to Redis Pub/Sub ({symbol}_event_channel)

    On closed candle (kline['x'] == True):
      - Appends OHLC data to the internal candle buffer
      - Calls on_candle(buffer) if a callback is provided
    """

    def __init__(
        self,
        symbol: str,
        interval: str,
        candle_buffer_size: int = -1,          # -1 = unlimited; N = keep last N candles
        on_candle: Optional[Callable] = None,  # Callback invoked with the full buffer on each closed candle
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.candle_buffer_size = candle_buffer_size
        self.on_candle = on_candle

        self._candle_buffer: list = []
        self._redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

    async def listen(self) -> None:
        """Open the WebSocket connection and process messages until disconnected."""
        uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_{self.interval}"
        async with websockets.connect(uri) as websocket:
            while True:
                data = await websocket.recv()
                json_data = json.loads(data)
                kline = json_data['k']

                # Publish live price on every tick so Trade can track floating P&L
                active_data = {
                    'event_time': json_data['E'],
                    'symbol':     json_data['s'],
                    'live_price': float(kline['c']),
                    'interval':   kline['i'],
                }
                self._redis_client.publish(
                    f"{self.symbol}_event_channel",
                    json.dumps(active_data)
                )

                # Only process completed candles (x = is closed)
                if kline['x']:
                    self._candle_buffer.append({
                        'high':       float(kline['h']),
                        'low':        float(kline['l']),
                        'open':       float(kline['o']),
                        'close':      float(kline['c']),
                        'close_time': kline['T'],
                    })

                    # Evict oldest candle if buffer limit is set
                    if self.candle_buffer_size >= 0 and len(self._candle_buffer) > self.candle_buffer_size:
                        self._candle_buffer.pop(0)

                    if self.on_candle:
                        self.on_candle(self._candle_buffer)