from pydantic import BaseModel


class Candle(BaseModel):
    high: float
    low: float
    open: float
    close: float
    close_time: int