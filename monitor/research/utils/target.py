from tabulate import tabulate


capital = 250   # trade size
income_target = 100  # in dollars
target_per_trade = 1.5 # profit in percentage
spot_trading_fees = 0.10 # in percentage (for each buy or sell)


profit_per_trade = capital * target_per_trade / 100
fees_per_trade = capital * (spot_trading_fees / 100 ) * 2 
net_profit = profit_per_trade - fees_per_trade
number_of_trades = income_target / net_profit

print("Summary")
data = [
    ["Target Size", capital, "USD"],
    ["Income Target", income_target, "USD"],
    ["Target per Trade (%)", target_per_trade, "%"],
    ["Spot Trading Fees (%)", spot_trading_fees, "%"],
    ["Profit per Trade", profit_per_trade, "USD"],
    ["Fees per Trade", fees_per_trade, "USD"],
    ["Net Profit per Trade", net_profit, "USD"],
    ["Number of Trades Needed to Reach Target", number_of_trades]
]

print(tabulate(data, headers=["Metric", "Value", "Unit"], tablefmt="grid"))

# print(f"Profit per trade: {profit_per_trade}")
# print(f"Fees per trade: {fees_per_trade}")
# print(f"Net profit per trade: {net_profit}")
# print(f"Number of trades needed to reach the profit target: {number_of_trades}")

