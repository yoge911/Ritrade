import streamlit as st

st.set_page_config(page_title="vbout/ Walkthrough", layout="wide")

st.title("`vbout/` — Architecture Overview")
st.markdown("---")

st.markdown("""
Your instinct is right. This is an evolution toward a **complete, integrated trading system** — moving from passive observation (`candle_roll.py`) toward active execution. The directory name likely stands for **"volatility breakout"**.
""")

st.markdown("---")
st.header("The Execution Flow")

st.code("""main.py
  ├── Kline (kline.py)         — WebSocket feed, publishes live price to Redis Pub/Sub
  ├── strategy.py              — volatility_breakout logic (acts on closed candles)
  └── Trade (trade.py)
        ├── PnL (PnL.py)       — stop/target math and floating P&L
        └── listens to Redis Pub/Sub for live price updates (from Kline)""", language="text")

st.markdown("---")
st.header("File by File")

st.subheader("`main.py` — The orchestrator. Wires everything together:")
st.markdown("""
- Hardcoded to `solusdc` (not BTC — this was tested on a different pair)
- Creates a `Kline` listener with an `on_candle` callback → calls `handle_listener` → calls `volatility_breakout`
- Also instantiates a `Trade` object (which starts monitoring immediately on creation)
- `breakout_logs` is written to Redis as `"breakout_logs"` — this is what the `pages/voltaility breakout.py` dashboard page reads
""")

st.subheader("`kline.py` — The market data layer. A clean `Kline` class that:")
st.markdown("""
- Subscribes to Binance `@kline_1m` WebSocket
- On **every tick** (open candle): publishes `live_price` + `event_time` to a Redis Pub/Sub channel (`{symbol}_event_channel`) — this is what `Trade` listens to for real-time price monitoring
- On **candle close**: appends to `candle_buffer` and calls the `on_candle` callback — this is what feeds `strategy.py`
- `candle_buffer_size=-1` means unlimited accumulation (all history kept)
""")

st.subheader("`strategy.py` — The strategy logic. A simple **range breakout**:")
st.markdown("""
- Looks at all prior closed candles to find `recent_high` and `recent_low`
- If the latest candle closes **above** prior highs → `breakoutUp` (long signal)
- If it closes **below** prior lows → `breakoutDown` (short signal)
- Logs each candle's result to `breakout_logs`
- Note: this is **not** the volatility trap strategy from `candle_roll.py` — it's a different, simpler strategy based on price range breakout on 1m candles
""")

st.subheader("`PnL.py` — Pure math module for trade management:")
st.markdown("""
- Takes `entry_price`, `account_balance`, `quantity`, `risk_percent`, `reward_percent`
- Derives `stop_price` and `target_price` from risk/reward math (not from chart structure)
- `check_price(current_price)` returns a live snapshot: floating P&L, zone (Profit/Loss), distance to SL/TP
""")

st.subheader("`trade.py` — The trade lifecycle manager:")
st.markdown("""
- Spawns a **background thread** (`monitor_thread`) that subscribes to the Redis Pub/Sub channel
- On each live price tick from `Kline`, calls `PnL.check_price()` and writes the result to `hmset("{ticker}_status")` in Redis
- Has stubs for `execute_limit_order`, `execute_market_order`, `autocontrol` — these are **not implemented yet**
- `close_trade()` publishes a `"trade_closed"` event back to the channel to shut down the listener
""")

st.subheader("`smc.py` — A standalone experiment, **not integrated** into `main.py`:")
st.markdown("""
- Connects directly to Binance `@kline_1m` WebSocket on `btcusdt`
- Implements **SMC (Smart Money Concepts) / RIMC detection** — range identification, initiation, mitigation, and continuation signals using rolling window logic on a pandas DataFrame
- Has a live Matplotlib animation that plots close price and highlights continuation signals
- Essentially a research prototype for a different strategy direction
""")

st.subheader("`smcplot.py` — An incomplete extract of the plotting logic from `smc.py`.")
st.markdown("""
Missing `import pandas as pd` and the `df` variable is referenced but not defined — this was in the middle of being refactored out of `smc.py` and was never finished.
""")

st.subheader("`util/format.py` — Shared timestamp formatter, the only utility extracted into a module so far.")

st.markdown("---")
st.header("What's Missing to Integrate the Volatility Trap")

st.markdown("""
Your read is correct — the gap between `vbout/` and `candle_roll.py` is that `strategy.py` currently implements a **price range breakout**, not the **volatility trap**. To bring them together you'd need to:

1. Replace or augment `strategy.py` with the trap logic from `candle_roll.py` — specifically the rolling 10s window, `dynamic_factor`, and the authenticity check (volume + trade count + std_dev thresholds)
2. The `Kline` class uses `@kline_1m` (closed candle events) — the trap fires at **20s into each minute** from raw `@trade` stream data, so `Kline` would need to be replaced or supplemented with a trade-stream equivalent (like `candle_roll.py`'s WebSocket loop)
3. `Trade` already has the skeleton for acting on signals — `execute_limit_order` / `execute_market_order` just need implementing once a trap signal fires
""")
