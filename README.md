# Ritrade

An automated cryptocurrency trading system built around a **volatility trap strategy** on 1-minute candles. Split into two independent layers that communicate via Redis.

- **`monitor/`** — passive observation: signal generation, Redis publishing, NiceGUI dashboard
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
Evaluate entry via strategy
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
monitor/activity_monitor.py  →  Redis  →  execute/breakout/main.py
                                       →  monitor/app.py          (NiceGUI, read-only, port 8081)
                                       →  execute/trade/dashboard.py  (NiceGUI, interactive, port 8080)
```

### Redis Keys

| Key | Written by | Read by | Content |
|---|---|---|---|
| `rolling_metrics_logs` | `activity_monitor.py` | `monitor/app.py` tab 1 | Rolling 10s window metrics |
| `trap_logs` | `activity_monitor.py` | `monitor/app.py` tab 2 | 20s trap snapshots |
| `minute_logs` | `activity_monitor.py` | `monitor/app.py` tab 3 | Per-minute summaries |
| `{ticker}_activity_snapshots` | `activity_monitor.py` (pending) | `trade/dashboard.py` signals table | Per-ticker activity scores |
| `{ticker}_status` | `services/trade.py` (hset) | `trade/dashboard.py` pinned panels | Full trade state: price, P&L, SL, TP, decisions |
| `{ticker}_event_channel` | `services/kline.py` (pub) | `services/trade.py` (sub) | Live price ticks via Pub/Sub |
| `execution_commands` | `trade/dashboard.py` (pub) | `breakout/main.py` (sub) | JSON commands: pin, order, cancel, close |
| `execution_pinned_tickers` | `breakout/main.py` (sadd/srem) | `breakout/main.py` (smembers) | Set of pinned tickers, persisted across restarts |

### Execute Layer Flow

```
execute/breakout/main.py  →  ExecutionController
  ├── loads tickers_config.json            — list of supported tickers
  ├── subscribes to execution_commands     — pin/unpin, place/cancel/close orders
  ├── restores execution_pinned_tickers    — persisted pinned set across restarts
  └── per pinned ticker:
        ├── Kline (services/kline.py)      — WebSocket @kline_1m; publishes live_price to Redis
        └── Trade (services/trade.py)
              ├── state machine: idle → pending_entry → open → closed
              ├── ManualEntryStrategy      — validates entry, derives stop/target
              ├── FixedStopExitStrategy    — monitors stop hit
              ├── ExecutionService         — thin actuator: open/close/modify_stop
              └── PnLCalculator            — stop/target math and floating P&L per tick
```

### Execute Package Layout

```
execute/
  models/                 — pure data shapes (Pydantic BaseModel)
    trade_config.py       TradeConfig
    candle.py             Candle
    breakout_log.py       BreakoutLog
    price_status.py       PriceLevels  (dashboard-facing Redis hash shape)
    trade_runtime.py      TradeState, MarketSnapshot, EntryDecision, ExitDecision, type aliases

  services/               — behaviour / orchestration
    kline.py              Kline          (WebSocket + Redis pub; stop() for graceful shutdown)
    pnl_calculator.py     PnLCalculator  (stop/target/P&L math; returns PriceLevels)
    trade.py              Trade          (thread + Redis sub + state machine + strategy wiring)
    execution.py          ExecutionService  (thin actuator: open/close/modify_stop)

  strategy/               — pluggable strategy layer
    base.py               EntryStrategy (ABC), ExitStrategy (ABC)
    fixed_stop.py         FixedStopExitStrategy
    manual_entry.py       ManualEntryStrategy

  breakout/
    main.py               ExecutionController entry point
    strategy.py           volatility_breakout function (not currently wired into main.py)

  trade/
    dashboard.py          NiceGUI dashboard (port 8080)
    dashboard.css         styles

  smc/
    smc.py / smcplot.py   research prototypes
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
│   ├── activity_monitor.py         # Core signal engine — rolling 10s window, trap at 20s
│   ├── candle.py                   # Older bucket-based engine (kept for reference)
│   ├── app.py                      # NiceGUI monitor dashboard (3 tabs, port 8081)
│   ├── signal_score.py             # Standalone 0–100 signal scorer (not yet integrated)
│   ├── volume_spike.py             # Independent volume spike audio alerts
│   ├── volatility.py               # Pre-trade ticker selection (top 20 USDT pairs)
│   ├── prices.py                   # Early price prototype (superseded)
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
│   │   ├── price_status.py         # PriceLevels — Redis hash shape read by dashboard
│   │   └── trade_runtime.py        # TradeState, MarketSnapshot, EntryDecision, ExitDecision
│   ├── services/                   # Behaviour / orchestration
│   │   ├── kline.py                # Kline — WebSocket feed; publishes price to Redis Pub/Sub
│   │   ├── pnl_calculator.py       # PnLCalculator — stop/target math and floating P&L
│   │   ├── trade.py                # Trade — state machine + strategy orchestration
│   │   └── execution.py            # ExecutionService — thin actuator (open/close/modify_stop)
│   ├── strategy/                   # Pluggable strategy layer
│   │   ├── base.py                 # EntryStrategy + ExitStrategy ABCs
│   │   ├── fixed_stop.py           # FixedStopExitStrategy
│   │   └── manual_entry.py         # ManualEntryStrategy
│   ├── breakout/
│   │   ├── main.py                 # ExecutionController entry point
│   │   └── strategy.py             # volatility_breakout logic (not yet wired into main.py)
│   ├── trade/
│   │   ├── dashboard.py            # NiceGUI dashboard — pinned panels + signals table
│   │   └── dashboard.css           # Dashboard styles
│   └── smc/
│       ├── smc.py                  # SMC/RIMC detection research prototype
│       └── smcplot.py              # Matplotlib plot extraction (work in progress)
│
├── tests/                          # pytest suite
│   ├── conftest.py                 # sys.path setup, FakeRedis stub
│   └── test_trade_runtime.py       # Trade lifecycle tests
│
├── archive/
│   └── candle_old.py               # Superseded bucket-based candle engine
│
├── simulations/
│   └── bracketing_income.py        # Standalone income/bracketing simulation
│
├── tickers_config.json             # Calibrated thresholds per ticker (BTCUSDC, SOLUSDC)
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

Stops any existing processes first, then starts all four components in the background. Logs are written to `.run/*.log` and PIDs tracked in `.run/*.pid`.

```
✅  Redis OK
▶  monitor/activity_monitor.py      (pid 12345)
▶  monitor/app.py                   (pid 12346)
▶  execute.breakout.main            (pid 12347)
▶  execute.trade.dashboard          (pid 12348)

Logs → .run/   |   Stop with: make stop
```

### Stop everything

```bash
make stop
```

### Tailing logs

```bash
tail -f .run/activity_monitor.log   # monitor signal engine
tail -f .run/monitor.log            # monitor NiceGUI dashboard
tail -f .run/main.log               # execute engine
tail -f .run/dashboard.log          # execute NiceGUI dashboard

tail -f .run/*.log                  # all at once
```

### Individual components (foreground, useful for debugging)

| Command | What it runs | Port |
|---|---|---|
| `make activity-monitor` | Monitor signal engine | — |
| `make monitor` | Monitor NiceGUI dashboard | 8081 |
| `make main` | Execute engine (Kline + Trade) | — |
| `make dashboard` | Execute NiceGUI dashboard | 8080 |
| `make volume-spike` | Volume spike audio alerts | — |
| `make volatility` | Ticker scorer → volatile_tickers.txt | — |

All targets that require Redis call `redis-check` first and fail fast if it is not up.

---

## Running Manually

### Monitor (run from `monitor/`)

```bash
cd monitor

python activity_monitor.py   # core signal engine — writes to Redis
python app.py                # NiceGUI monitor dashboard — reads from Redis (port 8081)

python volume_spike.py       # optional: volume spike audio alerts
python volatility.py         # optional: score top 20 pairs → volatile_tickers.txt
```

### Execute (run from repo root)

```bash
python -m execute.breakout.main      # execution engine
python -m execute.trade.dashboard    # NiceGUI dashboard (port 8080)
```

> Execute scripts use package-style imports and must be run as modules (`python -m`) from the repo root. Monitor scripts must be run from within `monitor/`.

---

## Control Flow: Manual vs Automated

The execute layer supports two control modes per trade:

| Mode | Behaviour |
|---|---|
| `manual` | Strategy decisions are computed and stored in `strategy_state` as recommendations, but not acted on. Human confirms via dashboard. |
| `automated` | Strategy decisions are applied immediately — limit fills, stop hits, and exit triggers execute without human input. |

`control_mode` is set at order placement (`submit_entry(initiated_by=..., control_mode=...)`) and can be overridden mid-trade. Any manual action (modify stop, close) automatically seizes manual control.

---

## Dashboards

### Monitor Dashboard (`monitor/app.py`) — port 8081

NiceGUI app. Read-only signal observer. Three tabs:

| Tab | Redis Key | Content |
|---|---|---|
| Micro Buckets (10s) | `rolling_metrics_logs` | Rolling 10s window metrics |
| 20s Trap Snapshots | `trap_logs` | WAP, std_dev, slope, volumes at trap time |
| 1-Minute Summary | `minute_logs` | Per-minute trade count, volume, buy/sell breakdown |

### Execution Dashboard (`execute/trade/dashboard.py`) — port 8080

Interactive execution surface. Two sections:

**Pinned Tickers** — one card per pinned ticker:
- Live Price, Floating P&L, Zone, Entry, Stop, Target
- Buy (long limit), Sell (short limit), Trail, Close buttons

**Monitoring Snapshots** — tabbed feed from monitor:
- 20s Snapshots: per-ticker activity score, qualified status, trades, volume, WAP, slope
- 1m Signal Snapshots: per-minute candle summary per ticker

---

## Ticker Configuration (`tickers_config.json`)

Repo-root JSON listing supported tickers with calibrated thresholds. Both the monitor and execute layers load from this file.

```json
[
  { "ticker": "BTCUSDC", "min_volume_threshold": ..., "max_volume_threshold": ..., ... },
  { "ticker": "SOLUSDC", ... }
]
```

The authenticity thresholds are specific to each ticker and were derived from baseline data in `monitor/research/`. Changing or adding a ticker requires recalibrating its thresholds.

---

## Signal Score (`monitor/signal_score.py`)

Standalone utility. Computes a **0–100 signal strength score** from:

| Component | Weight | Description |
|---|---|---|
| Volume ratio (buy/sell) | 50% | Pressure direction |
| Momentum | 30% | Rolling price change |
| Spread efficiency | 20% | Inverse of bid-ask spread |

Not yet integrated into the live engine.

---

## Next Integration Points

1. **Monitor → per-ticker snapshots**: `activity_monitor.py` needs to write `{ticker}_activity_snapshots` keys so the execute dashboard signals table shows live data.
2. **strategy.py wiring**: `execute/breakout/strategy.py` (`volatility_breakout`) is not currently called — wiring it into `ExecutionController.start_kline` would enable automated breakout detection per ticker.

---

## Infrastructure

- **Binance WebSocket** — live trade stream (`@trade`) and kline stream (`@kline_1m`)
- **Redis** — in-memory message bus shared between monitor and execute layers (port 6379)
- **NiceGUI** — both monitor and execution dashboards
