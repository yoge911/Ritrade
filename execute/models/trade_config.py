from typing import Literal
from pydantic import BaseModel, field_validator


class TradeConfig(BaseModel):
    ticker: str
    interval: str
    strategy: str
    account_balance: float
    entry_price: float
    quantity: float
    risk_percent: float = 1
    reward_percent: float = 2
    position_type: Literal['long', 'short'] = 'long'

    @field_validator('position_type', mode='before')
    @classmethod
    def normalise_position_type(cls, v: str) -> str:
        return v.lower()