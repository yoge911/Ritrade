from datetime import datetime
from typing import Literal, Optional
import threading
import redis
import json
from execute.services.pnl_calculator import PnLCalculator
from core_utils.format import format_timestamp


class Trade:
    """
    Represents an open trade position. On instantiation it:
      1. Records the trade start time (begin)
      2. Spins up a PnLCalculator for stop/target math
      3. Starts a background thread that subscribes to the ticker's Redis
         Pub/Sub channel and writes live P&L status on every price tick
    """

    def __init__(
        self,
        ticker: str,
        entry_price: float,
        account_balance: float,
        quantity: float,
        position_type: Literal['long', 'short'] = 'long',
        risk_percent: float = 1,
        reward_percent: float = 2,
    ) -> None:
        self.ticker = ticker
        self.entry_price = entry_price
        self.account_balance = account_balance
        self.quantity = quantity
        self.position_type = position_type.lower()
        self.risk_percent = risk_percent
        self.reward_percent = reward_percent
        self.status = 'open'  # 'open' | 'closed'

        # Runtime state — not part of trade data, just wiring
        self._redis_client = redis.Redis(host='localhost', port=6379, db=0)
        self._pnl_calculator: Optional[PnLCalculator] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._trade_start: Optional[str] = None

        self.begin()
        self.monitor_trade()

    # ── Price monitoring ──────────────────────────────────────────────────────

    def listen_price_updates(self) -> None:
        """
        Blocking loop — runs in a daemon thread.
        Subscribes to {ticker}_event_channel and writes P&L to Redis on each tick.
        Exits when a 'trade_closed' event is received.
        """
        pubsub = self._redis_client.pubsub()
        pubsub.subscribe(f"{self.ticker}_event_channel")
        print(f"[{self.ticker}] Listening for price updates on Redis channel.")

        for message in pubsub.listen():
            if message['type'] != 'message':
                continue

            try:
                data = json.loads(message['data'])
            except (ValueError, json.JSONDecodeError):
                print(f"[{self.ticker}] Invalid JSON: {message['data']}")
                continue

            if data.get('event') == 'trade_closed':
                print(f"[{self.ticker}] Received trade closed event.")
                break

            elif 'live_price' in data:
                current_price = float(data['live_price'])
                result = self._pnl_calculator.check_price(current_price)
                print(result)
                # Write full PriceStatus to Redis hash — dashboard reads this
                self._redis_client.hset(f"{self.ticker}_status", mapping=result.model_dump())

            else:
                print(f"[{self.ticker}] Ignored unrecognized message: {data}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def begin(self) -> None:
        """Record the trade start timestamp."""
        self._trade_start = format_timestamp(int(datetime.now().timestamp()))
        print(f"[{self.ticker}] Starting trade...")

    def monitor_trade(self) -> None:
        """Instantiate PnLCalculator and start the price monitoring thread."""
        self._pnl_calculator = PnLCalculator(
            ticker=self.ticker,
            entry_price=self.entry_price,
            account_balance=self.account_balance,
            quantity=self.quantity,
            risk_percent=self.risk_percent,
            reward_percent=self.reward_percent,
            position_type=self.position_type,
        )
        self._monitor_thread = threading.Thread(target=self.listen_price_updates)
        self._monitor_thread.daemon = True  # dies automatically when main process exits
        self._monitor_thread.start()

    def execute_limit_order(self) -> None:
        # Placeholder for limit order execution logic
        pass

    def execute_market_order(self) -> None:
        # Placeholder for market order execution logic
        pass

    def close_trade(self) -> None:
        """Mark trade as closed and publish a close event to the channel."""
        self.status = 'closed'
        print(f"[{self.ticker}] Trade closed.")
        # Notify the listen_price_updates thread so it exits its loop
        self._redis_client.publish(
            f"{self.ticker}_event_channel",
            json.dumps({"event": "trade_closed"})
        )

    def autocontrol(self) -> None:
        # Placeholder for auto-control logic
        pass