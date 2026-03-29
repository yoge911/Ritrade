import streamlit as st

st.set_page_config(page_title="How It Works", layout="wide")

st.title("How Ritrade Works")
st.markdown("A step-by-step walkthrough of the codebase and trading strategy.")
st.markdown("---")

st.header("Step 1: Calibrating Thresholds — `tickerstat.py`")
st.markdown("""
Before anything runs live, you first **collected baseline data**. `tickerstat.py` connects to Binance's
WebSocket for a ticker, records trade count, total volume, and price std deviation every 20 seconds
for 1 hour, then saves it to a CSV.

This is where the magic numbers in `candle.py` come from:

| Threshold | Value |
|---|---|
| `min_auth_volume` | 0.1003 |
| `max_auth_volume` | 1.1916 |
| `min_trade_count` | 24 |
| `max_trade_count` | 295 |
| `min_std_dev` | 0.004749 |
| `max_std_dev` | 4.0196 |

You ran this script to observe what "normal" BTCUSDC looks like, then used those CSV files as your
reference range. The `.csv` files in the project root are those baselines.
""")

st.divider()

st.header("Step 2: Picking the Right Ticker — `volatility.py`")
st.markdown("""
Before trading, the top 20 crypto pairs on Binance are scored to find the best one to trade right now.
It fetches the last 15 one-minute candles for each pair and scores them by:

- **Price movement** (×2.5 weight)
- **Quote volume** (log-scaled)
- **Average spread** (penalty ×1.5)
- **Low volume penalty** if quote volume < $500,000

The top 5 scoring tickers are saved to `volatile_tickers.txt`. This is the **ticker selection layer** —
the data decides which pair to trade, not a hardcoded value.
""")

st.divider()

st.header("Step 3: The Core Engine — `candle.py` vs `activity_monitor.py`")
st.markdown("""
The strategy was written in two versions, both sharing the same core idea but differing in how they
measure the 20-second window.
""")

col1, col2 = st.columns(2)

with col1:
    st.subheader("candle.py — Bucket-Based")
    st.markdown("""
Every trade goes into **two buffers simultaneously**:
- A `master_*` buffer that accumulates the whole minute
- A `bucket_*` buffer that resets every 10 seconds

This gives you a view of "what happened this full minute so far" AND "what happened in this specific 10-second slice" at the same time.
""")

with col2:
    st.subheader("activity_monitor.py — Rolling Window")
    st.markdown("""
Instead of fixed buckets, this keeps a **rolling list of trades from the last 10 seconds**, trimming
old ones on every new trade. The window is always "the last 10 seconds from right now" — not "this
10-second bucket."

It also logs a metric snapshot on **every single trade**, giving the dashboard a much smoother,
more continuous picture.
""")

st.divider()

st.header("Step 4: The 20-Second Trap Decision")
st.markdown("""
At exactly **20 seconds into each minute** (detected via `event_time % 60000`), the engine snapshots
everything collected so far and runs the **authenticity check**:

| Check | Condition | Purpose |
|---|---|---|
| Volume range | `min_auth_volume < volume < max_auth_volume` | Filters no-activity and anomalies |
| Trade count | `trade_count > min_trade_count` | Rules out single whale trades |
| Std deviation | `min_std_dev < std_dev < max_std_dev` | Confirms real price movement |

If all three pass, the market is considered **authentic** — real participants moving the price.

The engine then computes a `dynamic_factor` (0 to 1) by normalizing each of the three values against
your baselines and averaging them. This tells you **how strong** the signal is, not just whether it passed.

The snapshot — avg price, WAP, std dev, slope, buy/sell volumes — is saved as a trap log entry and
pushed to Redis.
""")

st.divider()

st.header("Step 5: Signal Scoring — `signal_score.py`")
st.markdown("""
A separate, more refined scoring module. Given a DataFrame of price, buy volume, sell volume, and spread,
it computes a **micro signal score out of 100**:
""")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Volume Ratio (Buy/Sell)", "50%", help="Who's winning the tug-of-war")
with col2:
    st.metric("Rolling Momentum", "30%", help="Is price actually moving?")
with col3:
    st.metric("Spread Efficiency", "20%", help="Tight spread = cleaner signal")

st.markdown("""
This is designed to be called on the rolling 10-second window data, giving a single number that
summarizes overall signal quality.
""")

st.divider()

st.header("Step 6: Volume Spike Alerts — `volume_spike.py`")
st.markdown("""
This runs as a **separate, always-on script** watching BTC, ETH, SOL, and BNB simultaneously via a
combined WebSocket stream.

**Logic:**
- Waits for a *closed* 1-minute candle
- Checks if its volume is more than **2× the average of the last 10 candles**
- If yes → plays an audio alert and logs the spike

This is the **early warning system**, running independently of the main trap engine.
""")

st.divider()

st.header("Step 7: The Dashboard — `app.py`")
st.markdown("""
The Streamlit dashboard reads three Redis keys written by the core engine and refreshes every second:

| Tab | Content |
|---|---|
| Micro Buckets (10s) | Continuous rolling window metrics |
| 20s Trap Snapshots | One row per minute — the decision log |
| 1-Minute Summary | Trade count, buy/sell volumes per candle |

The bot and the dashboard are **completely decoupled via Redis**. The engine just writes;
the UI just reads. Either side can be swapped without touching the other.
""")

st.divider()

st.header("Step 8: Simulation & Planning Tools")

col1, col2 = st.columns(2)
with col1:
    st.subheader("`target.py`")
    st.markdown("""
A simple sanity-check calculator. Given:
- Capital amount
- Profit target %
- Fee rate

It tells you **how many trades you need** to hit your income target after fees.
""")

with col2:
    st.subheader("`simulations/bracketing_income.py`")
    st.markdown("""
More advanced. Simulates hourly P&L across different scenarios:
- **Win rates:** 60%, 65%, 70%, 75%
- **Trade frequency:** 60, 120, 180 trades/hour

Helps answer: which combinations are actually profitable after fees?
""")

st.divider()

st.header("How It All Fits Together")
st.code("""
volatility.py         → pick the best ticker to trade
tickerstat.py         → calibrate thresholds for that ticker
        ↓
activity_monitor.py        → live WebSocket engine: collect trades,
                        run authenticity check, fire traps at 20s
        ↓
Redis                 → shared memory between bot and UI
        ↓
app.py                → live dashboard reading from Redis

volume_spike.py       → runs in parallel, watches for big volume events
signal_score.py       → scoring utility (callable on any window of data)
target.py             → offline trade count calculator
simulations/          → offline P&L scenario planner
""", language="text")

st.caption("Ritrade — Internal Documentation")
