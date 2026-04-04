import json

from market_data.channels import execution_price_channel
from execute.services.pnl_calculator import PnLCalculator
from execute.services.trade import Trade
from execute.strategy.fixed_stop import FixedStopExitStrategy
from execute.strategy.manual_entry import ManualEntryStrategy


class FakeRedis:
    def __init__(self, *args, **kwargs) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.published: list[tuple[str, str]] = []

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes[key] = dict(mapping)

    def delete(self, key: str) -> None:
        self.hashes.pop(key, None)

    def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    def pubsub(self, *args, **kwargs):
        raise AssertionError('pubsub should not be used in unit tests')


def build_trade(monkeypatch) -> Trade:
    monkeypatch.setattr('execute.services.trade.redis.Redis', FakeRedis)
    entry = ManualEntryStrategy(
        account_balance=10000,
        quantity=100,
        risk_percent=1,
        reward_percent=2,
    )
    return Trade(
        ticker='btcusdc',
        account_balance=10000,
        quantity=100,
        risk_percent=1,
        reward_percent=2,
        entry_strategy=entry,
        exit_strategy=FixedStopExitStrategy(),
    )


def test_entry_strategy_shapes_manual_request(monkeypatch):
    trade = build_trade(monkeypatch)

    ok, message = trade.submit_entry('long', 100.0)

    assert ok is True
    assert message == 'LONG limit order placed.'
    assert trade.state.lifecycle_state == 'pending_entry'
    assert trade.state.initiated_by == 'manual'
    assert trade.state.control_mode == 'manual'
    assert trade.state.limit_price == 100.0
    assert trade.state.stop_price == 99.0
    assert trade.state.entry_decision == 'keep_pending'


def test_manual_control_blocks_automated_fill_and_logs_recommendation(monkeypatch):
    trade = build_trade(monkeypatch)
    trade.submit_entry('long', 100.0)

    trade.handle_live_price(99.5)

    assert trade.state.lifecycle_state == 'pending_entry'
    assert trade.state.entry_decision == 'open_long'
    assert trade.state.strategy_state['entry_recommendation']['action'] == 'open_long'


def test_automated_pending_entry_fills_and_opens_position(monkeypatch):
    trade = build_trade(monkeypatch)
    trade.submit_entry('long', 100.0, initiated_by='automated', control_mode='automated')

    trade.handle_live_price(99.5)

    assert trade.state.lifecycle_state == 'open'
    assert trade.state.initiated_by == 'automated'
    assert trade.state.control_mode == 'automated'
    assert trade.state.entry_price == 100.0
    assert trade.state.stop_price == 99.0
    assert trade.state.target_price == 102.0
    assert trade.state.entry_decision == 'open_long'


def test_automated_open_trade_closes_when_stop_is_hit(monkeypatch):
    trade = build_trade(monkeypatch)
    trade.submit_entry('long', 100.0, initiated_by='automated', control_mode='automated')
    trade.handle_live_price(99.5)

    trade.handle_live_price(98.9)

    assert trade.state.lifecycle_state == 'closed'
    assert trade.state.exit_decision == 'exit_now'
    assert trade.state.zone == 'Closed'


def test_manual_command_overrides_automated_control(monkeypatch):
    trade = build_trade(monkeypatch)
    trade.submit_entry('long', 100.0, initiated_by='automated', control_mode='automated')
    trade.handle_live_price(99.5)

    ok, message = trade.modify_stop(99.4)

    assert ok is True
    assert message == 'Stop updated.'
    assert trade.state.control_mode == 'manual'
    assert trade.state.manual_override_active is True
    assert trade.state.stop_price == 99.4

    trade.handle_live_price(99.35)

    assert trade.state.lifecycle_state == 'open'
    assert trade.state.strategy_state['exit_recommendation']['action'] == 'exit_now'


def test_status_serialization_keeps_dashboard_fields(monkeypatch):
    trade = build_trade(monkeypatch)
    trade.submit_entry('short', 200.0, initiated_by='automated', control_mode='automated')
    trade.handle_live_price(200.5)
    trade.write_status()

    status = trade._redis_client.hashes['btcusdc_status']

    for field in [
        'state',
        'position',
        'live_price',
        'limit_price',
        'entry_price',
        'stop_price',
        'target_price',
        'pnl',
        'zone',
        'last_update',
        'initiated_by',
        'control_mode',
        'entry_strategy',
        'exit_strategy',
        'entry_decision',
        'exit_decision',
        'decision_reason',
        'manual_override_active',
        'strategy_state',
        'stop_mode',
    ]:
        assert field in status

    assert status['state'] == 'open'
    assert status['position'] == 'short'
    assert status['initiated_by'] == 'automated'
    assert status['control_mode'] == 'automated'
    assert json.loads(status['strategy_state'])['stop_mode'] == 'initial'


def test_pnl_calculator_is_pure_math_helper():
    levels = PnLCalculator.derive_levels(
        entry_price=100.0,
        account_balance=10000,
        quantity=100,
        risk_percent=1,
        reward_percent=2,
        position_type='long',
    )

    pnl = PnLCalculator.calculate_floating_pnl(
        position_type='long',
        entry_price=100.0,
        current_price=101.25,
        quantity=100,
    )

    assert round(levels.stop_price, 5) == 99.0
    assert round(levels.target_price, 5) == 102.0
    assert pnl == 125.0


def test_trade_accepts_trade_compatibility_live_price_payload(monkeypatch):
    trade = build_trade(monkeypatch)
    trade.submit_entry('long', 100.0, initiated_by='automated', control_mode='automated')

    trade.handle_live_price(float({
        'event_type': 'trade',
        'event_time': 1710000020000,
        'symbol': 'btcusdc',
        'live_price': 99.5,
    }['live_price']))

    assert trade.state.lifecycle_state == 'open'
    assert trade.state.live_price == 99.5


def test_trade_shutdown_uses_execution_price_channel(monkeypatch):
    trade = build_trade(monkeypatch)

    trade.shutdown()

    assert trade._redis_client.published == [
        (execution_price_channel(trade.state.ticker), json.dumps({'event': 'shutdown_listener'}))
    ]
