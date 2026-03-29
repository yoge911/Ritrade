from pydantic import BaseModel


class BreakoutLog(BaseModel):
    timestamp: str
    high: float
    low: float
    open: float
    close: float
    breakoutUp: bool
    breakoutDown: bool