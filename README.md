# Ritrade

An automated cryptocurrency trading system built around a **volatility trap strategy** on 1-minute candles. Split into two independent layers that communicate via Redis.

- **`monitor/`** — passive observation: signal generation, Redis publishing, Streamlit dashboard
- **`execute/`** — active execution: strategy evaluation, trade lifecycle, NiceGUI dashboard

---

## How It Works

### Strategy: Volatility Trap

Ritrade monitors live trade data from Binance and identifies authentic momentum windows at the 20-second mark of each candle.

**Flow per 1-minute candle:**

```
New 1-Min Candle Opens
        ↓
Start Collecting Trade Data (rolling 10s window)
        ↓
     At 20s:
Authenticity check: volume, trade count, std_dev within calibrated thresholds
        ↓
  If Authentic:                   Else:
Compute dynamic_factor        Skip This Candle
Fire trap snapshot → Redis
        ↓
Execute layer reads signal
Evaluate volatility breakout
Manage trade lifecycle (SL / TP)
```

### Signal Authenticity

The monitor distinguishes real momentum from noise:

| Condition | Meaning | Action |
|---|---|---|
| High std_dev + high trade frequency | Real momentum | Fire trap, compute dynamic_factor |
| High std_dev + low trade frequency | Manipulated / fake | Skip |
| Low std_dev + steady frequency | Calm market | Skip |

### dynamic_factor

A 0–1 score computed as the average of three normalized values (volume, std_dev, trade_count), each banded at the 20th–80th percentile of calibrated baseline data.

---

## Architecture

### Data Flow

```
monitor/candle_roll.py  →  Redis  →  execute/breakout/main.py
                                  →  monitor/app.py        (Streamlit, read-only)
                                  →  execute/trade/dashboard.py  (NiceGUI, interactive)
```

### Redis Keys

| Key | Written by | Read by | Content |
|---|---|---|---|
| `trap_logs` | `candle_roll.py` | `app.py` tab 2, `execute/trade/dashboard.py` | 20s trap snapshots |
| `minute_logs` | `candle_roll.py` | `app.py` tab 3 | per-minute summaries |
| `rolling_metrics_logs` | `candle_roll.py` | `app.py` tab 1 | rolling 10s metrics |
| `breakout_logs` | `breakout/strategy.py` | `trade/dashboard.py` | per-candle breakout signal log |
| `{ticker}_status` | `services/trade.py` | `trade/dashboard.py` | live trade status: price, P&L, SL, TP |
| `{ticker}_event_channel` | `services/kline.py` (pub) | `services/trade.py` (sub) | live price ticks via Pub/Sub |

### Execute Layer Flow

```
execute/breakout/main.py
  ├── Kline (services/kline.py)       — WebSocket @kline_1m feed; publishes live_price to Redis Pub/Sub
  ├── strategy.py                     — volatility_breakout on closed candles → writes breakout_logs to Redis
  └── Trade (services/trade.py)
        ├── PnLCalculator             — stop/target math and floating P&L per tick
        │   (services/pnl_calculator.py)
        └── subscribes to {ticker}_event_channel for live price updates
```

### Execute Package Layout

```
execute/
  models/               ← pure data shapes (Pydantic BaseModel)
    trade_config.py     TradeConfig
    candle.py           Candle
    breakout_log.py     BreakoutLog
    price_status.py     PriceStatus

  services/             ← behaviour / orchestration (plain Python classes)
    kline.py            Kline          (WebSocket + Redis pub)
    pnl_calculator.py   PnLCalculator  (stop/target/P&L math)
    trade.py            Trade          (thread + Redis sub + lifecycle)

  breakout/
    main.py             entry point
    strategy.py         volatility_breakout function

  trade/
    dashboard.py        NiceGUI dashboard

  smc/
    smc.py / smcplot.py  research prototypes
```

### Time Windows

- `master_*` — metrics accumulated across the full minute
- `bucket_*` — metrics scoped to a single 10-second window
- `already_triggered_20s` — guard flag ensuring the trap fires only once per minute
- WAP (weighted average price) is used instead of simple average throughout

---

## Project Structure

```
Ritrade/
├── core_utils/                     # Shared utilities (used by both layers)
│   ├── format.py                   # format_timestamp(ms)
│   ├── logger/log.py               # Timestamped logger
│   └── tones/                      # Audio files for macOS afplay alerts
│
├── monitor/                        # Passive observation layer
│   ├── candle_roll.py              # Core signal engine — rolling 10s window, trap at 20s
│   ├── candle.py                   # Older bucket-based engine (kept for reference)
│   ├── app.py                      # Streamlit dashboard (3 tabs, reads from Redis)
│   ├── signal_score.py             # Standalone 0–100 signal scorer (not yet integrated)
│   ├── volume_spike.py             # Independent volume spike audio alerts
│   ├── volatility.py               # Pre-trade ticker selection (top 20 USDT pairs)
│   ├── prices.py                   # Early price prototype (superseded by candle_roll.py)
│   ├── pages/
│   │   ├── how_it_works.py         # Streamlit page: monitor codebase walkthrough
│   │   └── vbout_walkthrough.py    # Streamlit page: execute codebase walkthrough
│   └── research/
│       ├── tickerstat.py           # Archived baseline data collector
│       ├── thresh.ipynb            # Threshold calibration notebook
│       ├── *_baseline_*.csv        # Baseline data used to calibrate thresholds
│       ├── volatile_tickers.txt    # Output of volatility.py
│       └── utils/
│           ├── target.py           # Research: TP/SL target utility
│           └── vbout.py            # Research: volatility breakout utility
│
├── execute/                        # Active execution layer
│   ├── models/                     # Pure data shapes (Pydantic BaseModel)
│   │   ├── trade_config.py         # TradeConfig — ticker, interval, risk/reward params
│   │   ├── candle.py               # Candle — OHLC + close_time
│   │   ├── breakout_log.py         # BreakoutLog — per-candle breakout signal
│   │   └── price_status.py         # PriceStatus — live P&L snapshot written to Redis
│   ├── services/                   # Behaviour / orchestration (plain Python classes)
│   │   ├── kline.py                # Kline — WebSocket feed; publishes price to Redis Pub/Sub
│   │   ├── pnl_calculator.py       # PnLCalculator — stop/target math and floating P&L
│   │   └── trade.py                # Trade — lifecycle: open, monitor, close
│   ├── breakout/
│   │   ├── main.py                 # Entry point: wires Kline + strategy + Trade
│   │   └── strategy.py             # volatility_breakout logic on closed candles
│   ├── trade/
│   │   └── dashboard.py            # NiceGUI dashboard: trade cards, breakout log, Buy/Sell
│   └── smc/
│       ├── smc.py                  # SMC/RIMC detection research prototype
│       └── smcplot.py              # Matplotlib plot extraction (work in progress)
│
├── archive/
│   └── candle_old.py               # Superseded bucket-based candle engine
│
├── simulations/
│   └── bracketing_income.py        # Standalone income/bracketing simulation
│
├── Makefile                        # Start / stop / run individual components
├── requirements.txt
└── .env
```

---

## Setup

### Prerequisites

- Python 3.12+
- Redis running locally on port 6379

```bash
# Install Redis (macOS)
brew install redis
brew services start redis

# Install Python dependencies
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running with Make

The Makefile is the recommended way to start the system.

### Start everything

```bash
make start
```

Starts the three core processes in the background. Logs are written to `.run/*.log` and PIDs tracked in `.run/*.pid`.

```
✅  Redis OK
▶  monitor/candle_roll.py      (pid 12345)
▶  execute.breakout.main        (pid 12346)
▶  execute.trade.dashboard      (pid 12347)

Logs → .run/   |   Stop with: make stop
```

### Stop everything

```bash
make stop
```

### Verify processes are running

After `make start`, confirm all three processes are alive:

```bash
ps aux | grep -E "candle_roll|execute.breakout|execute.trade" | grep -v grep
```

Expected output — one line per process:

```
user  12345  ...  python monitor/candle_roll.py
user  12346  ...  python -m execute.breakout.main
user  12347  ...  python -m execute.trade.dashboard
```

If a process is missing it crashed on startup — check its log (see below).

You can also verify the NiceGUI dashboard came up by checking its log directly:

```bash
cat .run/dashboard.log
# NiceGUI ready to go on http://localhost:8080, and http://192.168.x.x:8080
```

### Tailing logs

Each process writes to its own log file in `.run/`. Tail them individually:

```bash
tail -f .run/candle_roll.log   # monitor signal engine
tail -f .run/main.log          # execute engine
tail -f .run/dashboard.log     # NiceGUI dashboard
```

To watch all three at once:

```bash
tail -f .run/*.log
```

`tail -f` will show the filename header when multiple files are tailed together, so you can tell which process each line came from.

### Individual components (foreground, useful for debugging)

| Command | What it runs |
|---|---|
| `make candle-roll` | Monitor signal engine |
| `make main` | Execute engine (Kline + strategy + trade) |
| `make dashboard` | NiceGUI trade dashboard |
| `make streamlit` | Streamlit monitor dashboard |
| `make volume-spike` | Volume spike audio alerts |
| `make volatility` | Ticker scorer |

All targets that require Redis call `redis-check` first and fail fast if it is not up.

---

## Running Manually

### Monitor (run from `monitor/`)

```bash
cd monitor

python candle_roll.py          # core signal engine — writes to Redis
streamlit run app.py           # Streamlit dashboard — reads from Redis

python volume_spike.py         # optional: volume spike audio alerts
python volatility.py           # optional: score top 20 pairs → volatile_tickers.txt
```

### Execute (run from repo root)

```bash
python -m execute.breakout.main      # execution engine
python -m execute.trade.dashboard    # NiceGUI dashboard
```

> Execute scripts use package-style imports and must be run as modules (`python -m`) from the repo root. Monitor scripts must be run from within `monitor/`.

---

## Signal Score (`monitor/signal_score.py`)

Standalone utility that computes a **0–100 signal strength score** from:

| Component | Weight | Description |
|---|---|---|
| Volume ratio (buy/sell) | 50% | Pressure direction |
| Momentum | 30% | Rolling price change |
| Spread efficiency | 20% | Inverse of bid-ask spread |

Not yet integrated into the live engine.

---

## Ticker Selection (`monitor/volatility.py`)

Scans the top 20 market-cap USDT pairs on Binance and scores them by:

- Price change over last 15 candles (×2.5 weight)
- Quote volume (log-scaled)
- Average spread penalty (×1.5)
- Low volume penalty if quote volume < $500,000

Top 5 tickers are saved to `monitor/research/volatile_tickers.txt`.

---

## Calibrated Thresholds

The authenticity thresholds in `candle_roll.py` are specific to **BTCUSDC** and were derived from baseline data in `monitor/research/`. The archived `tickerstat.py` generated those `.csv` files. Changing the ticker requires recalibrating all threshold values.

---

## Dashboards

### Streamlit (`monitor/app.py`)

Reads from Redis, auto-refreshes. Three tabs:

| Tab | Content |
|---|---|
| Micro Buckets (10s) | Rolling 10s window metrics (`rolling_metrics_logs`) |
| 20s Trap Snapshots | Trap trigger data: WAP, std_dev, slope, volumes (`trap_logs`) |
| 1-Minute Summary | Per-minute trade count, volume, buy/sell breakdown (`minute_logs`) |

Additional pages auto-loaded by Streamlit from `pages/`.

### NiceGUI (`execute/trade/dashboard.py`)

Interactive execution UI. Runs standalone on port 8080:

- Live trade status cards (price, P&L, SL, TP)
- Breakout log table
- Buy / Sell buttons

---

## Next Integration Point

`execute/breakout/strategy.py` currently implements a simple price range breakout. The calibrated volatility trap logic from `monitor/candle_roll.py` (including `dynamic_factor` and authenticity checks) has not yet been ported into the execute layer. This is the next planned integration.

---

## Infrastructure

- **Binance WebSocket** — live trade stream (`@trade`) and kline stream (`@kline_1m`)
- **Redis** — in-memory message bus shared between monitor and execute layers
- **Streamlit** — monitor dashboard
- **NiceGUI** — execution dashboard