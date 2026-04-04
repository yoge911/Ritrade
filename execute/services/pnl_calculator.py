from __future__ import annotations

import json
from typing import Literal

from execute.models.price_status import PriceLevels
from execute.models.trade_runtime import TradeState


class TradeLevels:
    def __init__(self, *, stop_price: float, target_price: float) -> None:
        self.stop_price = stop_price
        self.target_price = target_price


class PnLCalculator:
    """Pure helper for stop/target math and floating P&L display data."""

    @staticmethod
    def derive_levels(
        *,
        entry_price: float,
        account_balance: float,
        quantity: float,
        risk_percent: float = 1,
        reward_percent: float = 2,
        position_type: Literal['long', 'short'] = 'long',
    ) -> TradeLevels:
        risk_amount = account_balance * (risk_percent / 100)
        reward_amount = account_balance * (reward_percent / 100)
        risk_reward_ratio = reward_amount / risk_amount if risk_amount else 0
        stop_distance = risk_amount / quantity if quantity else 0

        if position_type.lower() == 'long':
            stop_price = entry_price - stop_distance
            target_price = entry_price + (stop_distance * risk_reward_ratio)
        else:
            stop_price = entry_price + stop_distance
            target_price = entry_price - (stop_distance * risk_reward_ratio)

        return TradeLevels(stop_price=stop_price, target_price=target_price)

    @staticmethod
    def calculate_floating_pnl(
        *,
        position_type: Literal['long', 'short'],
        entry_price: float,
        current_price: float,
        quantity: float,
    ) -> float:
        if position_type == 'long':
            return (current_price - entry_price) * quantity
        return (entry_price - current_price) * quantity

    @classmethod
    def build_status(cls, state: TradeState, *, last_update: str) -> PriceLevels:
        live_price = round(state.live_price, 5) if state.live_price is not None else None
        limit_price = round(state.limit_price, 5) if state.limit_price is not None else None
        entry_price = round(state.entry_price, 5) if state.entry_price is not None else None
        stop_price = round(state.stop_price, 5) if state.stop_price is not None else None
        target_price = round(state.target_price, 5) if state.target_price is not None else None

        pnl = state.pnl
        if state.lifecycle_state == 'open' and state.live_price is not None and state.entry_price is not None and state.position:
            pnl = cls.calculate_floating_pnl(
                position_type=state.position,
                entry_price=state.entry_price,
                current_price=state.live_price,
                quantity=state.quantity,
            )

        zone = 'Flat'
        if state.lifecycle_state == 'closed':
            zone = 'Closed'
        elif state.lifecycle_state == 'pending_entry':
            zone = 'Pending'
        elif pnl > 0:
            zone = 'Profit'
        elif pnl < 0:
            zone = 'Loss'

        return PriceLevels(
            ticker=state.ticker,
            is_pinned=state.is_pinned,
            state=state.lifecycle_state,
            position=state.position,
            live_price=live_price,
            limit_price=limit_price,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            pnl=round(pnl, 2),
            zone=zone,
            quantity=state.quantity,
            risk_percent=state.risk_percent,
            reward_percent=state.reward_percent,
            initiated_by=state.initiated_by,
            control_mode=state.control_mode,
            entry_strategy=state.entry_strategy,
            exit_strategy=state.exit_strategy,
            entry_decision=state.entry_decision,
            exit_decision=state.exit_decision,
            decision_reason=state.decision_reason,
            manual_override_active=state.manual_override_active,
            strategy_state=json.dumps(state.strategy_state, sort_keys=True),
            stop_mode=str(state.strategy_state.get('stop_mode', '')),
            last_update=last_update,
        )
