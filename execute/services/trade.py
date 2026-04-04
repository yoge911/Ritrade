from datetime import datetime
from typing import Literal, Optional
import threading
import redis
import json

from execute.models.trade_runtime import ManualEntryIntent, MarketSnapshot, TradeControlMode, TradeState
from execute.services.execution import ExecutionService
from execute.services.pnl_calculator import PnLCalculator
from execute.strategy.base import EntryStrategy, ExitStrategy
from core_utils.format import format_timestamp


class Trade:
    def __init__(
        self,
        ticker: str,
        account_balance: float,
        quantity: float,
        position_type: Literal['long', 'short'] = 'long',
        risk_percent: float = 1,
        reward_percent: float = 2,
        entry_strategy: EntryStrategy | None = None,
        exit_strategy: ExitStrategy | None = None,
        execution_service: ExecutionService | None = None,
    ) -> None:
        self.account_balance = account_balance
        self.state = TradeState(
            ticker=ticker,
            quantity=quantity,
            risk_percent=risk_percent,
            reward_percent=reward_percent,
            created_at=self.timestamp(),
            updated_at=self.timestamp(),
        )
        self.entry_strategy = entry_strategy
        self.exit_strategy = exit_strategy
        self.execution_service = execution_service or ExecutionService()

        self._redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self._monitor_thread: Optional[threading.Thread] = None
        self._trade_start: Optional[str] = None
        self._running = threading.Event()

    def start(self) -> None:
        """Start the price-listener thread and publish the initial status."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._running.set()
        self.begin()
        self._monitor_thread = threading.Thread(target=self.listen_price_updates)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()
        self.write_status()

    def listen_price_updates(self) -> None:
        """Consume Redis price events and route live prices into the runtime."""
        pubsub = self._redis_client.pubsub()
        pubsub.subscribe(f"{self.state.ticker}_event_channel")
        print(f"[{self.state.ticker}] Listening for price updates on Redis channel.")

        for message in pubsub.listen():
            if not self._running.is_set():
                break

            if message['type'] != 'message':
                continue

            try:
                data = json.loads(message['data'])
            except (ValueError, json.JSONDecodeError):
                print(f"[{self.state.ticker}] Invalid JSON: {message['data']}")
                continue

            if data.get('event') == 'shutdown_listener':
                break

            elif 'live_price' in data:
                self.handle_live_price(float(data['live_price']))

            else:
                print(f"[{self.state.ticker}] Ignored unrecognized message: {data}")

        pubsub.close()

    def begin(self) -> None:
        """Record the runtime start timestamp for this trade instance."""
        self._trade_start = format_timestamp(int(datetime.now().timestamp() * 1000))
        print(f"[{self.state.ticker}] Starting trade...")

    def shutdown(self) -> None:
        """Stop the listener thread and unblock Redis pubsub shutdown cleanly."""
        self._running.clear()
        self._redis_client.publish(
            f"{self.state.ticker}_event_channel",
            json.dumps({"event": "shutdown_listener"})
        )
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)

    def has_active_trade(self) -> bool:
        """Return whether this ticker is currently pending or open."""
        return self.state.has_active_trade()

    def pin(self) -> None:
        """Mark the ticker as pinned and persist the updated status."""
        self.state.is_pinned = True
        self.write_status()

    def unpin(self) -> None:
        """Clear the pinned flag and persist the updated status."""
        self.state.is_pinned = False
        self.write_status()

    def place_limit_order(self, position_type: Literal['long', 'short'], limit_price: Optional[float] = None) -> tuple[bool, str]:
        """Backward-compatible wrapper for manual entry submission."""
        return self.submit_entry(position_type, limit_price, initiated_by='manual', control_mode='manual')

    def submit_entry(
        self,
        position_type: Literal['long', 'short'],
        limit_price: Optional[float] = None,
        *,
        initiated_by: Literal['manual', 'automated'] = 'manual',
        control_mode: TradeControlMode | None = None,
    ) -> tuple[bool, str]:
        """Validate an entry request, move into pending state, and evaluate it immediately."""
        if not self.entry_strategy:
            return False, 'Entry strategy is not configured.'

        resolved_control_mode = control_mode or ('manual' if initiated_by == 'manual' else 'automated')
        if initiated_by == 'manual':
            self.take_manual_control(reason='Manual entry requested.')

        intent = ManualEntryIntent(side=position_type.lower(), limit_price=limit_price)
        snapshot = self.market_snapshot()
        decision = self.entry_strategy.evaluate_manual_entry(intent, self.state, snapshot)
        self.state.entry_strategy = self.entry_strategy.name
        self.state.entry_decision = decision.action
        self.state.decision_reason = decision.reason
        self.state.is_manual = initiated_by == 'manual'

        if not decision.is_valid:
            self.write_status()
            return False, decision.reason or 'Entry request rejected.'

        self.state.position = position_type.lower()
        self.state.initiated_by = initiated_by
        self.state.control_mode = resolved_control_mode
        self.state.manual_override_active = resolved_control_mode == 'manual'
        self.state.limit_price = round(decision.entry_price, 5) if decision.entry_price is not None else None
        self.state.entry_price = None
        self.state.stop_price = round(decision.initial_stop_price, 5) if decision.initial_stop_price is not None else None
        self.state.target_price = None
        self.state.pnl = 0.0
        self.state.lifecycle_state = 'pending_entry'
        self.state.strategy_state = {'stop_mode': 'initial', 'entry_metadata': decision.metadata}
        self.state.updated_at = snapshot.last_update
        self.write_status()
        self.evaluate_pending_entry(snapshot)
        return True, decision.reason or f'{position_type.upper()} limit order placed.'

    def cancel_order(self) -> tuple[bool, str]:
        """Cancel a pending entry and return the runtime to idle."""
        if self.state.lifecycle_state != 'pending_entry':
            return False, 'There is no pending order to cancel.'

        self.take_manual_control(reason='Manual order cancel requested.')
        self.state.lifecycle_state = 'idle'
        self.state.limit_price = None
        self.state.entry_price = None
        self.state.stop_price = None
        self.state.target_price = None
        self.state.pnl = 0.0
        self.state.zone = 'Flat'
        self.state.position = ''
        self.state.entry_decision = 'cancel_pending'
        self.state.decision_reason = 'Pending order cancelled.'
        self.state.strategy_state = {}
        self.write_status()
        return True, 'Pending order cancelled.'

    def close_position(self) -> tuple[bool, str]:
        """Close an open position immediately under manual control."""
        if self.state.lifecycle_state != 'open':
            return False, 'There is no open position to close.'

        self.take_manual_control(reason='Manual close requested.')
        self.execution_service.close_position(self.state, reason='Position closed.')
        self.state.closed_at = self.timestamp()
        self.state.exit_decision = 'exit_now'
        self.write_status()
        return True, 'Position closed.'

    def modify_stop(self, stop_price: float) -> tuple[bool, str]:
        """Apply a manual stop update and seize manual control."""
        if self.state.lifecycle_state != 'open':
            return False, 'There is no open position to update.'

        self.take_manual_control(reason='Manual stop update requested.')
        self.execution_service.modify_stop(self.state, stop_price=stop_price, reason='Stop updated manually.')
        self.state.exit_decision = 'move_stop'
        self.state.strategy_state['stop_mode'] = 'tightened' if self.state.position else self.state.strategy_state.get('stop_mode', 'initial')
        self.recompute_status(self.timestamp())
        self.write_status()
        return True, 'Stop updated.'

    def take_manual_control(self, *, reason: str = '') -> None:
        """Switch the trade into manual control mode immediately."""
        self.state.control_mode = 'manual'
        self.state.manual_override_active = True
        self.state.is_manual = True
        if reason:
            self.state.decision_reason = reason

    def release_manual_control(self) -> tuple[bool, str]:
        """Hand an active trade back to automated control."""
        if self.state.lifecycle_state not in {'pending_entry', 'open'}:
            return False, 'There is no active trade to hand back to automation.'

        self.state.control_mode = 'automated'
        self.state.manual_override_active = False
        self.state.decision_reason = 'Manual control released.'
        self.write_status()
        return True, 'Trade returned to automated control.'

    def handle_live_price(self, current_price: float) -> None:
        """Update live price, re-evaluate strategy flow, and persist status."""
        self.state.live_price = round(current_price, 5)
        snapshot = self.market_snapshot()
        self.state.updated_at = snapshot.last_update
        self.evaluate_pending_entry(snapshot)
        self.evaluate_exit(snapshot)
        self.write_status()

    def evaluate_pending_entry(self, snapshot: MarketSnapshot | None = None) -> None:
        """Ask the entry strategy how to handle the current pending setup."""
        if not self.entry_strategy or self.state.lifecycle_state != 'pending_entry':
            return
        decision = self.entry_strategy.evaluate_pending_entry(self.state, snapshot or self.market_snapshot())
        self.state.entry_strategy = self.entry_strategy.name
        self.state.entry_decision = decision.action
        self.state.decision_reason = decision.reason

        if self.state.control_mode != 'automated':
            self.state.strategy_state['entry_recommendation'] = {
                'action': decision.action,
                'entry_price': decision.entry_price,
                'initial_stop_price': decision.initial_stop_price,
                'reason': decision.reason,
            }
            return

        if decision.action in {'open_long', 'open_short'} and decision.entry_price is not None:
            self.open_position(decision.entry_price, decision.initial_stop_price)
            return

        if decision.action == 'cancel_pending':
            self.cancel_order()
            return

    def evaluate_exit(self, snapshot: MarketSnapshot | None = None) -> None:
        """Ask the exit strategy whether to hold, adjust stop, or exit."""
        if not self.exit_strategy or self.state.lifecycle_state != 'open':
            self.recompute_status(snapshot.last_update if snapshot else self.timestamp())
            return

        decision = self.exit_strategy.evaluate(self.state, snapshot or self.market_snapshot())
        self.state.exit_strategy = self.exit_strategy.name
        self.state.exit_decision = decision.action
        self.state.decision_reason = decision.reason

        if self.state.control_mode != 'automated':
            self.state.strategy_state['exit_recommendation'] = {
                'action': decision.action,
                'stop_price': decision.stop_price,
                'reason': decision.reason,
            }
            self.recompute_status(snapshot.last_update if snapshot else self.timestamp())
            return

        stop_mode_map = {
            'move_stop': 'initial',
            'move_to_break_even': 'breakeven',
            'tighten_stop': 'tightened',
            'trail_stop': 'trailing',
        }
        if decision.action in stop_mode_map and decision.stop_price is not None:
            self.execution_service.modify_stop(self.state, stop_price=decision.stop_price, reason=decision.reason)
            self.state.strategy_state['stop_mode'] = stop_mode_map[decision.action]
        elif decision.action == 'exit_now':
            self.execution_service.close_position(self.state, reason=decision.reason)
            self.state.closed_at = snapshot.last_update if snapshot else self.timestamp()

        self.recompute_status(snapshot.last_update if snapshot else self.timestamp())

    def open_position(self, entry_price: float, stop_price: float | None) -> None:
        """Transition a filled entry into an open position and seed display levels."""
        self.execution_service.open_position(self.state, entry_price=entry_price, stop_price=stop_price)
        self.state.opened_at = self.timestamp()
        self.state.limit_price = self.state.limit_price
        self.state.strategy_state['stop_mode'] = 'initial'

        levels = PnLCalculator.derive_levels(
            entry_price=entry_price,
            account_balance=self.account_balance,
            quantity=self.state.quantity,
            risk_percent=self.state.risk_percent,
            reward_percent=self.state.reward_percent,
            position_type=self.state.position or 'long',
        )
        self.state.target_price = round(levels.target_price, 5)
        self.recompute_status(self.timestamp())

    def recompute_status(self, last_update: str) -> None:
        """Refresh derived PnL and zone fields from the current trade state."""
        status = PnLCalculator.build_status(self.state, last_update=last_update)
        self.state.pnl = status.pnl
        self.state.zone = status.zone

    def market_snapshot(self) -> MarketSnapshot:
        """Build the latest market snapshot passed into strategy evaluation."""
        return MarketSnapshot(
            ticker=self.state.ticker,
            live_price=self.state.live_price,
            last_update=self.timestamp(),
        )

    def timestamp(self) -> str:
        """Return the current timestamp formatted for Redis/dashboard consumers."""
        return format_timestamp(int(datetime.now().timestamp() * 1000))

    def write_status(self, status: Optional[object] = None) -> None:
        """Serialize the current runtime status into the Redis status hash."""
        if status is None:
            payload = PnLCalculator.build_status(self.state, last_update=self.timestamp()).model_dump()
        else:
            payload = status.model_dump()

        mapping = {
            key: '' if value is None else str(value)
            for key, value in payload.items()
        }
        self._redis_client.hset(f"{self.state.ticker}_status", mapping=mapping)

    def clear_status(self) -> None:
        """Remove the persisted Redis status for this ticker."""
        self._redis_client.delete(f"{self.state.ticker}_status")

    def autocontrol(self) -> None:
        """Placeholder hook for future higher-level automation orchestration."""
        pass
