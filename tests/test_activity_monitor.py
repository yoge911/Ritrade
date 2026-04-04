import asyncio
import json

from market_data.channels import (
    GLOBAL_MINUTE_LOGS_KEY,
    GLOBAL_ROLLING_METRICS_LOGS_KEY,
    GLOBAL_TRAP_LOGS_KEY,
    activity_snapshots_key,
    minute_logs_key,
    rolling_metrics_key,
    trade_events_channel,
)
from market_data.models import TradeEvent
from market_data.publishers.redis import RedisMarketDataPublisher
from monitor.activity_monitor import ActivityMonitor, TickerConfig


class FakePubSub:
    def __init__(self) -> None:
        self.channels: list[str] = []

    def subscribe(self, *channels: str) -> None:
        self.channels.extend(channels)

    def get_message(self, timeout: float | None = None):
        return None

    def close(self) -> None:
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.values: dict[str, str] = {}
        self.deleted: list[tuple[str, ...]] = []

    def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, *keys: str) -> None:
        self.deleted.append(keys)
        for key in keys:
            self.values.pop(key, None)

    def pubsub(self, *args, **kwargs) -> FakePubSub:
        return FakePubSub()


def build_config() -> TickerConfig:
    return TickerConfig(
        ticker='BTCUSDC',
        min_volume_threshold=0.1,
        max_volume_threshold=5.0,
        min_trade_count=1,
        max_trade_count=10,
        min_std_dev=0.01,
        max_std_dev=10.0,
    )


def build_trade_event(event_time: int, price: float, quantity: float) -> TradeEvent:
    return TradeEvent(
        symbol='btcusdc',
        event_time=event_time,
        price=price,
        quantity=quantity,
        is_buyer_maker=False,
    )


def test_activity_monitor_consumes_normalized_trade_events_and_writes_global_and_ticker_logs():
    fake_redis = FakeRedis()
    publisher = RedisMarketDataPublisher(fake_redis)
    monitor = ActivityMonitor([build_config()], fake_redis)
    monitor.initialize_redis()

    events = [
        build_trade_event(15000, 100.0, 0.20),
        build_trade_event(18000, 100.5, 0.25),
        build_trade_event(20050, 101.0, 0.30),
        build_trade_event(61000, 101.5, 0.35),
    ]

    for event in events:
        asyncio.run(publisher.publish_trade(event))
        normalized_payload = next(
            payload
            for channel, payload in reversed(fake_redis.published)
            if channel == trade_events_channel(event.symbol)
        )
        monitor.handle_trade_event(TradeEvent.model_validate_json(normalized_payload))

    activity_rows = json.loads(fake_redis.values[activity_snapshots_key('btcusdc')])
    minute_rows = json.loads(fake_redis.values[minute_logs_key('btcusdc')])
    rolling_rows = json.loads(fake_redis.values[rolling_metrics_key('btcusdc')])
    global_traps = json.loads(fake_redis.values[GLOBAL_TRAP_LOGS_KEY])
    global_minutes = json.loads(fake_redis.values[GLOBAL_MINUTE_LOGS_KEY])
    global_rolling = json.loads(fake_redis.values[GLOBAL_ROLLING_METRICS_LOGS_KEY])

    assert len(activity_rows) == 1
    assert activity_rows[0]['ticker'] == 'btcusdc'
    assert activity_rows[0]['timestamp'].endswith('00:20')
    assert activity_rows[0]['is_qualified_activity'] is True

    assert len(minute_rows) == 1
    assert minute_rows[0]['timestamp'].endswith('00:00')
    assert minute_rows[0]['trades'] == 3

    assert len(rolling_rows) == 4
    assert len(global_traps) == 1
    assert len(global_minutes) == 1
    assert len(global_rolling) == 4


def test_activity_monitor_rolls_window_to_last_ten_seconds():
    monitor = ActivityMonitor([build_config()], FakeRedis())

    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(5000, 101.0, 0.20),
        build_trade_event(16000, 102.0, 0.20),
    ]

    for event in events:
        monitor.handle_trade_event(event)

    state = monitor.states['btcusdc']
    assert [trade.event_time for trade in state.rolling_window_trades] == [16000]
