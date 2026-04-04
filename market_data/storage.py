from abc import ABC, abstractmethod

from market_data.models import KlineEvent, TradeEvent

MarketDataEvent = TradeEvent | KlineEvent


class StorageSink(ABC):
    @abstractmethod
    def persist(self, event: MarketDataEvent) -> None:
        """Persist a normalized event for future storage backends."""
