from __future__ import annotations

from execute.models.trade_runtime import ExitDecision, MarketSnapshot, TradeState
from execute.strategy.base import ExitStrategy


class FixedStopExitStrategy(ExitStrategy):
    name = 'fixed_stop'

    def evaluate(
        self,
        state: TradeState,
        snapshot: MarketSnapshot,
    ) -> ExitDecision:
        if state.lifecycle_state != 'open':
            return ExitDecision(reason='Trade is not open.')
        if snapshot.live_price is None or state.stop_price is None or not state.position:
            return ExitDecision(reason='Waiting for price or stop data.')

        hit_stop = (
            state.position == 'long' and snapshot.live_price <= state.stop_price
        ) or (
            state.position == 'short' and snapshot.live_price >= state.stop_price
        )
        if hit_stop:
            return ExitDecision(action='exit_now', reason='Stop price reached.')

        return ExitDecision(action='hold', reason='Hold position.')
