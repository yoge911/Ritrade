import asyncio
import json
from datetime import datetime, timezone

from market_data.channels import (
    MARKET_DATA_UPDATES_CHANNEL,
    execution_price_channel,
    kline_events_channel,
    latest_kline_event_key,
    latest_trade_event_key,
    trade_events_channel,
)
from market_data.models import KlineEvent, TradeEvent
from market_data.publishers.redis import RedisMarketDataPublisher
from market_data.sources.binance import BinanceKlineWebSocketSource, BinanceTradeWebSocketSource
from market_data.storage import JsonlTradeArchiveSink, StorageSink


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.values: dict[str, str] = {}

    def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


class RecordingStorageSink(StorageSink):
    def __init__(self) -> None:
        self.events: list[TradeEvent | KlineEvent] = []

    def persist(self, event: TradeEvent | KlineEvent) -> None:
        self.events.append(event)


def test_trade_payload_is_normalized_into_trade_event():
    payload = {
        's': 'BTCUSDC',
        'T': 1710000020000,
        'p': '62000.10',
        'q': '0.2500',
        'm': True,
    }

    event = BinanceTradeWebSocketSource.map_message(payload)

    assert event == TradeEvent(
        symbol='btcusdc',
        event_time=1710000020000,
        price=62000.10,
        quantity=0.25,
        is_buyer_maker=True,
    )


def test_kline_payload_is_normalized_into_kline_event():
    payload = {
        'E': 1710000060000,
        's': 'SOLUSDC',
        'k': {
            'i': '1m',
            'o': '120.10',
            'h': '121.50',
            'l': '119.95',
            'c': '121.10',
            'v': '1800.4',
            't': 1710000000000,
            'T': 1710000059999,
            'x': False,
            'n': 321,
        },
    }

    event = BinanceKlineWebSocketSource.map_message(payload)

    assert event == KlineEvent(
        symbol='solusdc',
        event_time=1710000060000,
        interval='1m',
        open=120.10,
        high=121.50,
        low=119.95,
        close=121.10,
        volume=1800.4,
        open_time=1710000000000,
        close_time=1710000059999,
        is_closed=False,
        trade_count=321,
    )


def test_redis_publisher_routes_events_to_expected_channels_and_storage():
    fake_redis = FakeRedis()
    storage = RecordingStorageSink()
    publisher = RedisMarketDataPublisher(fake_redis, storage_sink=storage, write_latest_snapshot=True)

    trade_event = TradeEvent(
        symbol='btcusdc',
        event_time=1710000020000,
        price=62000.10,
        quantity=0.25,
        is_buyer_maker=True,
    )
    kline_event = KlineEvent(
        symbol='btcusdc',
        event_time=1710000060000,
        interval='1m',
        open=62000.10,
        high=62010.00,
        low=61990.00,
        close=62005.50,
        volume=15.5,
        open_time=1710000000000,
        close_time=1710000059999,
        is_closed=False,
        trade_count=120,
    )

    asyncio.run(publisher.publish_trade(trade_event))
    asyncio.run(publisher.publish_kline(kline_event))

    assert storage.events == [trade_event, kline_event]

    published_channels = [channel for channel, _ in fake_redis.published]
    assert trade_events_channel('btcusdc') in published_channels
    assert kline_events_channel('btcusdc') in published_channels
    assert execution_price_channel('btcusdc') in published_channels
    assert MARKET_DATA_UPDATES_CHANNEL in published_channels

    assert json.loads(fake_redis.values[latest_trade_event_key('btcusdc')]) == trade_event.model_dump()
    assert json.loads(fake_redis.values[latest_kline_event_key('btcusdc')]) == kline_event.model_dump()

    compatibility_messages = [json.loads(payload) for channel, payload in fake_redis.published if channel == execution_price_channel('btcusdc')]
    assert len(compatibility_messages) == 1
    compatibility_payload = compatibility_messages[0]
    assert compatibility_payload == {
        'event_type': 'trade',
        'event_time': 1710000020000,
        'symbol': 'btcusdc',
        'live_price': 62000.1,
        'quantity': 0.25,
        'is_buyer_maker': True,
    }

    market_data_messages = [json.loads(payload) for channel, payload in fake_redis.published if channel == MARKET_DATA_UPDATES_CHANNEL]
    assert market_data_messages == [
        {
            'ticker': 'btcusdc',
            'event': 'latest_trade_updated',
        }
    ]


def test_jsonl_trade_archive_sink_rotates_by_ticker_and_utc_hour(tmp_path):
    sink = JsonlTradeArchiveSink(tmp_path)
    early_event = TradeEvent(
        symbol='btcusdc',
        event_time=int(datetime(2024, 1, 1, 0, 59, 59, tzinfo=timezone.utc).timestamp() * 1000),
        price=62000.1,
        quantity=0.25,
        is_buyer_maker=True,
    )
    late_event = TradeEvent(
        symbol='btcusdc',
        event_time=int(datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp() * 1000),
        price=62005.5,
        quantity=0.30,
        is_buyer_maker=False,
    )

    sink.persist(early_event)
    sink.persist(late_event)

    first_hour_files = list(tmp_path.rglob('00.jsonl'))
    second_hour_files = list(tmp_path.rglob('01.jsonl'))

    assert len(first_hour_files) == 1
    assert len(second_hour_files) == 1
    assert json.loads(first_hour_files[0].read_text().strip()) == early_event.model_dump()
    assert json.loads(second_hour_files[0].read_text().strip()) == late_event.model_dump()
