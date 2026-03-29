from typing import Literal
from execute.models.price_status import PriceStatus


class PnLCalculator:
    """
    Calculates stop/target prices and floating P&L per position type.
    All derived fields (stop/target prices, risk amounts) are computed in __init__.
    """

    def __init__(
        self,
        ticker: str,
        entry_price: float,
        account_balance: float,
        quantity: float,
        risk_percent: float = 1,    # % of account to risk per trade
        reward_percent: float = 2,  # % of account as target reward
        position_type: Literal['long', 'short'] = 'long',
    ) -> None:
        self.ticker = ticker
        self.entry_price = entry_price
        self.account_balance = account_balance
        self.quantity = quantity
        self.risk_percent = risk_percent
        self.reward_percent = reward_percent
        self.position_type = position_type.lower()

        # ── Derived fields ────────────────────────────────────────────────────

        # Dollar amounts derived from account balance percentages
        self.risk_amount = account_balance * (risk_percent / 100)
        self.reward_amount = account_balance * (reward_percent / 100)
        self.risk_reward_ratio = self.reward_amount / self.risk_amount

        # Stop distance in price units: how far price can move before the risk
        # amount is fully lost given the position size (quantity)
        self.stop_distance = self.risk_amount / quantity

        # Stop is below entry for longs, above for shorts; target is the mirror
        if self.position_type == 'long':
            self.stop_price   = entry_price - self.stop_distance
            self.target_price = entry_price + (self.stop_distance * self.risk_reward_ratio)
        else:  # short
            self.stop_price   = entry_price + self.stop_distance
            self.target_price = entry_price - (self.stop_distance * self.risk_reward_ratio)

        self.print_trade_summary()

    def print_trade_summary(self) -> None:
        print(f"--- Trade Monitor Setup for {self.ticker} ({self.position_type.upper()} POSITION) ---")
        print(f"Account Balance: ${self.account_balance}")
        print(f"Risk Amount: ${self.risk_amount}")
        print(f"Quantity: {self.quantity} units")
        print(f"Entry Price: ${self.entry_price}")
        print(f"Stop Price: ${self.stop_price}")
        print(f"Target Price: ${self.target_price}")
        print("-" * 40)

    def check_price(self, current_price: float) -> PriceStatus:
        """Check current price and return a PriceStatus model."""

        # Floating P&L: unrealised gain/loss at the current price
        # P&L at stop/target: fixed values that don't change tick-to-tick
        if self.position_type == 'long':
            floating_pnl  = (current_price    - self.entry_price) * self.quantity
            pnl_at_stop   = (self.stop_price   - self.entry_price) * self.quantity
            pnl_at_target = (self.target_price  - self.entry_price) * self.quantity
        else:  # short — profit when price falls
            floating_pnl  = (self.entry_price  - current_price)    * self.quantity
            pnl_at_stop   = (self.entry_price  - self.stop_price)   * self.quantity
            pnl_at_target = (self.entry_price  - self.target_price) * self.quantity

        return PriceStatus(
            position=self.position_type,
            entry_price=self.entry_price,
            zone='Profit' if floating_pnl > 0 else 'Loss',
            current_price=round(current_price, 2),
            sl=round(pnl_at_stop, 2),
            tp=round(pnl_at_target, 2),
            stop_price=round(self.stop_price, 2),
            target_price=round(self.target_price, 2),
            pnl=round(floating_pnl, 2),
        )