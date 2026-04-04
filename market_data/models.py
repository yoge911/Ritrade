from typing import Literal

from pydantic import BaseModel, ConfigDict


class TradeEvent(BaseModel):
    model_config = ConfigDict(extra='ignore')

    event_type: Literal['trade'] = 'trade'
    symbol: str
    event_time: int
    price: float
    quantity: float
    is_buyer_maker: bool


class KlineEvent(BaseModel):
    model_config = ConfigDict(extra='ignore')

    event_type: Literal['kline'] = 'kline'
    symbol: str
    event_time: int
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_time: int
    close_time: int
    is_closed: bool
    trade_count: int
