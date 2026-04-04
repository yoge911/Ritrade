from __future__ import annotations

from abc import ABC, abstractmethod

from execute.models.trade_runtime import (
    EntryDecision,
    ExitDecision,
    ManualEntryIntent,
    MarketSnapshot,
    TradeState,
)


class EntryStrategy(ABC):
    name = 'entry_strategy'

    @abstractmethod
    def evaluate_manual_entry(
        self,
        intent: ManualEntryIntent,
        state: TradeState,
        snapshot: MarketSnapshot,
    ) -> EntryDecision:
        raise NotImplementedError

    @abstractmethod
    def evaluate_pending_entry(
        self,
        state: TradeState,
        snapshot: MarketSnapshot,
    ) -> EntryDecision:
        raise NotImplementedError


class ExitStrategy(ABC):
    name = 'exit_strategy'

    @abstractmethod
    def evaluate(
        self,
        state: TradeState,
        snapshot: MarketSnapshot,
    ) -> ExitDecision:
        raise NotImplementedError
