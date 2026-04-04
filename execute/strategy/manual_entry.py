from __future__ import annotations

from execute.models.trade_runtime import EntryDecision, ManualEntryIntent, MarketSnapshot, TradeState
from execute.services.pnl_calculator import PnLCalculator
from execute.strategy.base import EntryStrategy


class ManualEntryStrategy(EntryStrategy):
    name = 'manual_entry'

    def __init__(
        self,
        *,
        account_balance: float,
        quantity: float,
        risk_percent: float,
        reward_percent: float,
    ) -> None:
        self.account_balance = account_balance
        self.quantity = quantity
        self.risk_percent = risk_percent
        self.reward_percent = reward_percent

    def evaluate_manual_entry(
        self,
        intent: ManualEntryIntent,
        state: TradeState,
        snapshot: MarketSnapshot,
    ) -> EntryDecision:
        if state.has_active_trade():
            return EntryDecision(reason='Ticker already has an active trade.')

        entry_price = intent.limit_price if intent.limit_price is not None else snapshot.live_price
        if entry_price is None:
            return EntryDecision(reason='No live price available yet for this ticker.')

        levels = PnLCalculator.derive_levels(
            entry_price=entry_price,
            account_balance=self.account_balance,
            quantity=self.quantity,
            risk_percent=self.risk_percent,
            reward_percent=self.reward_percent,
            position_type=intent.side,
        )
        return EntryDecision(
            action='open_long' if intent.side == 'long' else 'open_short',
            is_valid=True,
            entry_price=round(entry_price, 5),
            initial_stop_price=round(levels.stop_price, 5),
            reason=f'{intent.side.upper()} limit order placed.',
            metadata={'source': intent.source},
        )

    def evaluate_pending_entry(
        self,
        state: TradeState,
        snapshot: MarketSnapshot,
    ) -> EntryDecision:
        if state.lifecycle_state != 'pending_entry':
            return EntryDecision(action='no_trade', reason='No pending entry to evaluate.')
        if snapshot.live_price is None or state.limit_price is None or not state.position:
            return EntryDecision(action='keep_pending', is_valid=True, reason='Awaiting live price data.')

        should_fill = (
            state.position == 'long' and snapshot.live_price <= state.limit_price
        ) or (
            state.position == 'short' and snapshot.live_price >= state.limit_price
        )

        if not should_fill:
            return EntryDecision(action='keep_pending', is_valid=True, reason='Pending entry remains valid.')

        return EntryDecision(
            action='open_long' if state.position == 'long' else 'open_short',
            is_valid=True,
            entry_price=round(state.limit_price, 5),
            initial_stop_price=state.stop_price,
            reason='Pending entry filled.',
            metadata={'filled_from_pending': True},
        )
