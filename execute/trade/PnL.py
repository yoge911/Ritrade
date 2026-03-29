class PnLCalculator:
    """
    PnLCalculator calculates stop/target prices and floating P&L automatically per position type.
    """
    
    def __init__(self, ticker, entry_price, account_balance, quantity, risk_percent=1, reward_percent = 2, position_type='long'):
        self.ticker = ticker
        self.entry_price = entry_price
        self.account_balance = account_balance
        self.quantity = quantity
        self.reward_percent = reward_percent
        self.position_type = position_type.lower()  # ensure lowercase
        self.risk_percent = risk_percent
        
        self.risk_amount = self.account_balance * (self.risk_percent / 100)
        self.reward_amount = self.account_balance * (self.reward_percent / 100)
        self.risk_reward_ratio = self.reward_amount / self.risk_amount

        
        # Calculate stop distance
        self.stop_distance = self.risk_amount / self.quantity
        
        # Calculate stop/target prices depending on long or short
        if self.position_type == 'long':
            self.stop_price = self.entry_price - self.stop_distance
            self.target_price = self.entry_price + (self.stop_distance * self.risk_reward_ratio)
        elif self.position_type == 'short':
            self.stop_price = self.entry_price + self.stop_distance
            self.target_price = self.entry_price - (self.stop_distance * self.risk_reward_ratio)
        else:
            raise ValueError("position_type must be 'long' or 'short'")
        
        self.print_trade_summary()
    
    def print_trade_summary(self):
        print(f"--- Trade Monitor Setup for {self.ticker} ({self.position_type.upper()} POSITION) ---")
        print(f"Account Balance: ${self.account_balance}")
        print(f"Risk Amount: ${self.risk_amount}")
        print(f"Quantity: {self.quantity} units")
        print(f"Entry Price: ${self.entry_price}")
        print(f"Stop Price: ${self.stop_price}")
        print(f"Target Price: ${self.target_price}")
        print("-" * 40)
    
    def check_price(self, current_price, timestamp):
        """Check current price and return a consistent status report as dict."""

        if self.position_type == 'long':
            floating_pnl = (current_price - self.entry_price) * self.quantity
            pnl_at_stop = (self.stop_price - self.entry_price) * self.quantity
            pnl_at_target = (self.target_price - self.entry_price) * self.quantity
        else:  # short
            floating_pnl = (self.entry_price - current_price) * self.quantity 
            pnl_at_stop = (self.entry_price - self.stop_price) * self.quantity
            pnl_at_target = (self.entry_price - self.target_price) * self.quantity

        return {
            # "timestamp": timestamp,
            "position": self.position_type,
            "entry_price": self.entry_price,
            "Zone": "Profit" if floating_pnl > 0 else "Loss",
            "current_price": round(current_price, 2),
            "SL": round(pnl_at_stop, 2),
            "TP": round(pnl_at_target, 2),
            "Stop Price": round(self.stop_price,2),
            "Target Price": round(self.target_price,2),
            "PnL": round(floating_pnl, 2) 
        }


# Example usage:

# eth_trade = TradeCalculator(
#     ticker="ETHUSD",
#     entry_price=2000,
#     account_balance=15000,
#     quantity=1.5,
#     risk_reward_ratio=4,
#     position_type='short'  # ← specify 'short' or 'long'
# )


