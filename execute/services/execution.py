from __future__ import annotations

from execute.models.trade_runtime import TradeState


class ExecutionService:
    """Thin execution actuator that only applies requested state changes."""

    def open_position(self, state: TradeState, *, entry_price: float, stop_price: float | None) -> None:
        state.lifecycle_state = 'open'
        state.entry_price = round(entry_price, 5)
        state.stop_price = round(stop_price, 5) if stop_price is not None else None
        state.zone = 'Flat'

    def close_position(self, state: TradeState, *, reason: str = '') -> None:
        state.lifecycle_state = 'closed'
        state.limit_price = None
        state.zone = 'Closed'
        if reason:
            state.decision_reason = reason

    def modify_stop(self, state: TradeState, *, stop_price: float, reason: str = '') -> None:
        state.stop_price = round(stop_price, 5)
        if reason:
            state.decision_reason = reason
