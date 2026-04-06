from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from market_data.models import KlineEvent, TradeEvent

MarketDataEvent = TradeEvent | KlineEvent


class StorageSink(ABC):
    @abstractmethod
    def persist(self, event: MarketDataEvent) -> None:
        """Persist a normalized event for future storage backends."""


class JsonlTradeArchiveSink(StorageSink):
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def persist(self, event: MarketDataEvent) -> None:
        if not isinstance(event, TradeEvent):
            return

        archive_path = self._archive_path(event)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with archive_path.open('a') as archive_file:
            archive_file.write(json.dumps(event.model_dump()))
            archive_file.write('\n')
            archive_file.flush()

    def _archive_path(self, event: TradeEvent) -> Path:
        event_dt = datetime.fromtimestamp(event.event_time / 1000, tz=timezone.utc)
        return (
            self.root_dir
            / event.symbol.lower()
            / event_dt.strftime('%Y')
            / event_dt.strftime('%m')
            / event_dt.strftime('%d')
            / f'{event_dt.strftime("%H")}.jsonl'
        )
