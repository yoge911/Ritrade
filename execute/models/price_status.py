from pydantic import BaseModel


class PriceLevels(BaseModel):
    ticker: str
    is_pinned: bool
    state: str
    position: str
    live_price: float | None = None
    limit_price: float | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    pnl: float = 0.0
    zone: str = 'Flat'
    quantity: float
    risk_percent: float
    reward_percent: float
    initiated_by: str = ''
    control_mode: str = 'manual'
    entry_strategy: str = ''
    exit_strategy: str = ''
    entry_decision: str = ''
    exit_decision: str = ''
    decision_reason: str = ''
    manual_override_active: bool = False
    strategy_state: str = '{}'
    stop_mode: str = ''
    last_update: str
