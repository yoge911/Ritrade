import json

import redis

from market_data.channels import (
    execution_price_channel,
    kline_events_channel,
    latest_kline_event_key,
    latest_trade_event_key,
    trade_events_channel,
)
from market_data.models import KlineEvent, TradeEvent
from market_data.storage import MarketDataEvent, StorageSink


class RedisMarketDataPublisher:
    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        *,
        storage_sink: StorageSink | None = None,
        write_latest_snapshot: bool = False,
    ) -> None:
        self.redis_client = redis_client or redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.storage_sink = storage_sink
        self.write_latest_snapshot = write_latest_snapshot

    async def publish_trade(self, event: TradeEvent) -> None:
        self._persist(event)
        payload = json.dumps(event.model_dump())
        self.redis_client.publish(trade_events_channel(event.symbol), payload)
        if self.write_latest_snapshot:
            self.redis_client.set(latest_trade_event_key(event.symbol), payload)

        compatibility_payload = json.dumps({
            'event_type': event.event_type,
            'event_time': event.event_time,
            'symbol': event.symbol,
            'live_price': event.price,
            'quantity': event.quantity,
            'is_buyer_maker': event.is_buyer_maker,
        })
        self.redis_client.publish(execution_price_channel(event.symbol), compatibility_payload)

    async def publish_kline(self, event: KlineEvent) -> None:
        self._persist(event)
        payload = json.dumps(event.model_dump())
        self.redis_client.publish(kline_events_channel(event.symbol), payload)
        if self.write_latest_snapshot:
            self.redis_client.set(latest_kline_event_key(event.symbol), payload)

    def _persist(self, event: MarketDataEvent) -> None:
        if self.storage_sink:
            self.storage_sink.persist(event)
