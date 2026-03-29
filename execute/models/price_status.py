from pydantic import BaseModel


# Returned by PnLCalculator.check_price() on every price tick.
# Serialised directly to Redis via model_dump() — field names here are the Redis hash keys.

class PriceStatus(BaseModel):
    position: str        # 'long' or 'short'
    entry_price: float
    zone: str            # 'Profit' or 'Loss'
    current_price: float
    sl: float            # P&L at the stop level (negative = unrealised loss)
    tp: float            # P&L at the target level (positive = unrealised gain)
    stop_price: float    # Absolute stop price
    target_price: float  # Absolute target price
    pnl: float           # Floating P&L at current price