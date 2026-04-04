from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from market_data.models import KlineEvent, TradeEvent

TradeEventHandler = Callable[[TradeEvent], Awaitable[None]]
KlineEventHandler = Callable[[KlineEvent], Awaitable[None]]


class TradeEventSource(ABC):
    @abstractmethod
    async def run(self, on_event: TradeEventHandler) -> None:
        """Continuously emit normalized trade events to the provided handler."""


class KlineEventSource(ABC):
    @abstractmethod
    async def run(self, on_event: KlineEventHandler) -> None:
        """Continuously emit normalized kline events to the provided handler."""
