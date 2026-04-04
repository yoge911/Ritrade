import asyncio
import json

import websockets

from market_data.models import KlineEvent, TradeEvent
from market_data.sources.base import KlineEventHandler, KlineEventSource, TradeEventHandler, TradeEventSource

BINANCE_WS_BASE_URL = 'wss://stream.binance.com:9443/ws'


class BinanceTradeWebSocketSource(TradeEventSource):
    def __init__(self, symbol: str, *, reconnect_delay: float = 2.0) -> None:
        self.symbol = symbol.lower()
        self.reconnect_delay = reconnect_delay

    @property
    def uri(self) -> str:
        return f'{BINANCE_WS_BASE_URL}/{self.symbol}@trade'

    @staticmethod
    def map_message(payload: dict) -> TradeEvent:
        return TradeEvent(
            symbol=str(payload['s']).lower(),
            event_time=int(payload['T']),
            price=float(payload['p']),
            quantity=float(payload['q']),
            is_buyer_maker=bool(payload['m']),
        )

    async def run(self, on_event: TradeEventHandler) -> None:
        while True:
            try:
                async with websockets.connect(self.uri) as websocket:
                    while True:
                        message = await websocket.recv()
                        await on_event(self.map_message(json.loads(message)))
            except (websockets.ConnectionClosed, OSError):
                await asyncio.sleep(self.reconnect_delay)


class BinanceKlineWebSocketSource(KlineEventSource):
    def __init__(self, symbol: str, interval: str, *, reconnect_delay: float = 2.0) -> None:
        self.symbol = symbol.lower()
        self.interval = interval
        self.reconnect_delay = reconnect_delay

    @property
    def uri(self) -> str:
        return f'{BINANCE_WS_BASE_URL}/{self.symbol}@kline_{self.interval}'

    @staticmethod
    def map_message(payload: dict) -> KlineEvent:
        kline = payload['k']
        return KlineEvent(
            symbol=str(payload['s']).lower(),
            event_time=int(payload['E']),
            interval=str(kline['i']),
            open=float(kline['o']),
            high=float(kline['h']),
            low=float(kline['l']),
            close=float(kline['c']),
            volume=float(kline['v']),
            open_time=int(kline['t']),
            close_time=int(kline['T']),
            is_closed=bool(kline['x']),
            trade_count=int(kline['n']),
        )

    async def run(self, on_event: KlineEventHandler) -> None:
        while True:
            try:
                async with websockets.connect(self.uri) as websocket:
                    while True:
                        message = await websocket.recv()
                        await on_event(self.map_message(json.loads(message)))
            except (websockets.ConnectionClosed, OSError):
                await asyncio.sleep(self.reconnect_delay)
