from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TradeLifecycle = Literal['idle', 'pending_entry', 'open', 'closed']
PositionSide = Literal['long', 'short', '']
StopMode = Literal['', 'initial', 'breakeven', 'tightened', 'trailing']
TradeInitiator = Literal['manual', 'automated', '']
TradeControlMode = Literal['manual', 'automated']
EntryAction = Literal['open_long', 'open_short', 'keep_pending', 'cancel_pending', 'no_trade']
ExitAction = Literal['hold', 'move_stop', 'move_to_break_even', 'tighten_stop', 'trail_stop', 'exit_now']


class MarketSnapshot(BaseModel):
    ticker: str
    live_price: float | None = None
    last_update: str


class ManualEntryIntent(BaseModel):
    side: Literal['long', 'short']
    limit_price: float | None = None
    source: str = 'dashboard'


class EntryDecision(BaseModel):
    action: EntryAction = 'no_trade'
    is_valid: bool = False
    entry_price: float | None = None
    initial_stop_price: float | None = None
    reason: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExitDecision(BaseModel):
    action: ExitAction = 'hold'
    stop_price: float | None = None
    reason: str = ''
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradeState(BaseModel):
    ticker: str
    lifecycle_state: TradeLifecycle = 'idle'
    position: PositionSide = ''
    initiated_by: TradeInitiator = ''
    control_mode: TradeControlMode = 'manual'
    is_pinned: bool = False
    is_manual: bool = False
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
    created_at: str = ''
    opened_at: str = ''
    updated_at: str = ''
    closed_at: str = ''
    entry_strategy: str = ''
    exit_strategy: str = ''
    entry_decision: str = ''
    exit_decision: str = ''
    decision_reason: str = ''
    manual_override_active: bool = False
    strategy_state: dict[str, Any] = Field(default_factory=dict)

    def has_active_trade(self) -> bool:
        return self.lifecycle_state in {'pending_entry', 'open'}
