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
from monitor.activity_monitor import ActivityMonitor, QUALIFICATION_WINDOW_MS, ROLLING_LOG_RETENTION_MS, TickerConfig


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


def publish_and_handle(monitor: ActivityMonitor, publisher: RedisMarketDataPublisher, fake_redis: FakeRedis, event: TradeEvent) -> None:
    asyncio.run(publisher.publish_trade(event))
    normalized_payload = next(
        payload
        for channel, payload in reversed(fake_redis.published)
        if channel == trade_events_channel(event.symbol)
    )
    monitor.handle_trade_event(TradeEvent.model_validate_json(normalized_payload))


def test_activity_monitor_generates_setup_snapshot_from_full_qualification_window():
    fake_redis = FakeRedis()
    publisher = RedisMarketDataPublisher(fake_redis)
    monitor = ActivityMonitor([build_config()], fake_redis)
    monitor.initialize_redis()

    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.0, 0.20),
        build_trade_event(3000, 100.3, 0.20),
        build_trade_event(14000, 101.0, 0.20),
        build_trade_event(25000, 101.5, 0.20),
    ]

    for event in events:
        publish_and_handle(monitor, publisher, fake_redis, event)

    activity_rows = json.loads(fake_redis.values[activity_snapshots_key('btcusdc')])
    rolling_rows = json.loads(fake_redis.values[rolling_metrics_key('btcusdc')])
    global_traps = json.loads(fake_redis.values[GLOBAL_TRAP_LOGS_KEY])
    global_rolling = json.loads(fake_redis.values[GLOBAL_ROLLING_METRICS_LOGS_KEY])

    assert len(activity_rows) == 1
    assert activity_rows[0]['ticker'] == 'btcusdc'
    assert activity_rows[0]['timestamp'].endswith('00:23')
    assert activity_rows[0]['setup_start_time'].endswith('00:03')
    assert activity_rows[0]['setup_end_time'].endswith('00:23')
    assert activity_rows[0]['qualification_duration_ms'] == QUALIFICATION_WINDOW_MS
    assert activity_rows[0]['trigger_reason'] == 'rolling_snapshot_qualified'
    assert activity_rows[0]['trades'] == 2
    assert activity_rows[0]['volume'] == 0.4
    assert activity_rows[0]['is_qualified_activity'] is True

    # The rolling window at finalization time only contains the last trade,
    # and the stored snapshot excludes that late trade because it arrived after the cutoff.
    assert rolling_rows[-1]['trades'] == 1
    assert rolling_rows[-1]['volume'] == 0.2

    assert len(global_traps) == 1
    assert len(rolling_rows) == 5
    assert len(global_rolling) == 5


def test_activity_monitor_keeps_setup_active_until_first_trade_after_window():
    fake_redis = FakeRedis()
    monitor = ActivityMonitor([build_config()], fake_redis)

    trigger_events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.0, 0.20),
        build_trade_event(3000, 100.3, 0.20),
        build_trade_event(18000, 100.6, 0.20),
    ]

    for event in trigger_events:
        monitor.handle_trade_event(event)

    state = monitor.states['btcusdc']
    assert state.active_setup_start_time == 3000
    assert [trade.event_time for trade in state.active_setup_trades] == [3000, 18000]
    assert state.activity_snapshots == []

    final_event = build_trade_event(24000, 100.9, 0.20)
    monitor.handle_trade_event(final_event)

    assert state.active_setup_start_time is None
    assert state.active_setup_trades == []
    assert len(state.activity_snapshots) == 1
    assert state.activity_snapshots[0].timestamp.endswith('00:23')
    assert state.activity_snapshots[0].setup_end_time.endswith('00:23')
    assert state.activity_snapshots[0].qualification_duration_ms == QUALIFICATION_WINDOW_MS


def test_activity_monitor_finalizes_on_late_trade_but_clips_snapshot_to_window():
    monitor = ActivityMonitor([build_config()], FakeRedis())

    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.0, 0.20),
        build_trade_event(3000, 100.3, 0.20),
        build_trade_event(18000, 100.6, 0.20),
        build_trade_event(30000, 101.2, 0.20),
    ]

    for event in events:
        monitor.handle_trade_event(event)

    snapshot = monitor.states['btcusdc'].activity_snapshots[0]
    assert snapshot.timestamp.endswith('00:23')
    assert snapshot.setup_end_time.endswith('00:23')
    assert snapshot.qualification_duration_ms == QUALIFICATION_WINDOW_MS
    assert snapshot.trades == 2
    assert snapshot.volume == 0.4


def test_activity_monitor_does_not_retrigger_while_setup_is_active():
    monitor = ActivityMonitor([build_config()], FakeRedis())

    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.0, 0.20),
        build_trade_event(3000, 100.3, 0.20),
        build_trade_event(5000, 100.7, 0.20),
        build_trade_event(7000, 101.0, 0.20),
    ]

    for event in events:
        monitor.handle_trade_event(event)

    state = monitor.states['btcusdc']
    assert state.active_setup_start_time == 3000
    assert [trade.event_time for trade in state.active_setup_trades] == [3000, 5000, 7000]
    assert len(state.activity_snapshots) == 0


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


def test_activity_monitor_never_starts_setup_when_rolling_snapshot_is_not_qualified():
    config = TickerConfig(
        ticker='BTCUSDC',
        min_volume_threshold=10.0,
        max_volume_threshold=20.0,
        min_trade_count=5,
        max_trade_count=10,
        min_std_dev=2.0,
        max_std_dev=10.0,
    )
    monitor = ActivityMonitor([config], FakeRedis())

    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.1, 0.20),
        build_trade_event(25000, 100.2, 0.20),
    ]

    for event in events:
        monitor.handle_trade_event(event)

    state = monitor.states['btcusdc']
    assert state.active_setup_start_time is None
    assert state.activity_snapshots == []


def test_activity_monitor_writes_minute_logs_on_rollover():
    fake_redis = FakeRedis()
    monitor = ActivityMonitor([build_config()], fake_redis)
    monitor.initialize_redis()

    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.2, 0.20),
        build_trade_event(61000, 100.4, 0.20),
    ]

    for event in events:
        monitor.handle_trade_event(event)

    minute_rows = json.loads(fake_redis.values[minute_logs_key('btcusdc')])
    global_minutes = json.loads(fake_redis.values[GLOBAL_MINUTE_LOGS_KEY])

    assert len(minute_rows) == 1
    assert minute_rows[0]['timestamp'].endswith('00:00')
    assert minute_rows[0]['trades'] == 2
    assert len(global_minutes) == 1


def test_activity_monitor_exposes_qualification_window_constant():
    assert QUALIFICATION_WINDOW_MS == 20000


def test_activity_monitor_prunes_rolling_logs_older_than_two_minutes():
    monitor = ActivityMonitor([build_config()], FakeRedis())

    events = [
        build_trade_event(1000, 100.0, 0.20),
        build_trade_event(2000, 100.2, 0.20),
        build_trade_event(ROLLING_LOG_RETENTION_MS + 5000, 101.0, 0.20),
    ]

    for event in events:
        monitor.handle_trade_event(event)

    state = monitor.states['btcusdc']
    assert len(state.rolling_metrics_logs) == 1
    assert state.rolling_metrics_logs[0].event_time_ms == ROLLING_LOG_RETENTION_MS + 5000
    assert len(monitor.global_rolling_metrics_logs) == 1
    assert monitor.global_rolling_metrics_logs[0]['event_time_ms'] == ROLLING_LOG_RETENTION_MS + 5000
