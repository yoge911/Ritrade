# Re-run necessary setup since the code environment was reset

import pandas as pd
import numpy as np
import ace_tools_open as tools; 

from tabulate import tabulate
# Parameters for simulation ranges
capital = 500
trade_counts = [60, 120, 180]  # Number of trade setups per hour
win_rates = [0.6, 0.65, 0.7, 0.75]  # Different win rates to simulate
profit_per_win = 0.5
loss_per_loss = -0.3

# Prepare data for the simulator
data = []
for trades_per_hour in trade_counts:
    for win_rate in win_rates:
        wins = int(trades_per_hour * win_rate)
        losses = trades_per_hour - wins
        net_profit = (wins * profit_per_win + losses * loss_per_loss)
        data.append({
            "Capital (USD)": capital,
            "Trades/Hour": trades_per_hour,
            "Win Rate": f"{int(win_rate * 100)}%",
            "Wins": wins,
            "Losses": losses,
            "Net Hourly Profit (USD)": round(net_profit, 2)
        })

df_income_sim = pd.DataFrame(data)

table_output = tabulate(df_income_sim, headers='keys', tablefmt="fancy_outline", showindex=True)
print(table_output)
