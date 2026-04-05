# Ritrade

An automated cryptocurrency trading system built around a **microstructure-first volatility trap strategy**. Split into two independent layers that communicate via Redis.

## Goal

Ritrade is built to monitor live market activity, surface actionable trade setups, and then manage an open trade continuously until exit. The core idea is not just to detect an entry, but to keep reacting to market updates while the trade is alive:

```python
while trade_is_open:
    receive_market_update()
    update_trade_state()
    update_stop_logic()
    check_exit_conditions()

    if exit_required:
        execute_exit()
        break
```

In practice, that means the app aims to:
- detect meaningful market activity from live trade flow
- convert that activity into tradeable signals
- track open positions in real time
- keep stop and exit logic updated as price evolves
- close the trade when exit conditions are met

- **`monitor/`** — passive observation: signal generation from normalized Redis market data, NiceGUI dashboard
- **`market_data/`** — shared ingestion layer: Binance websocket retrieval, normalization, Redis publishing
- **`execute/`** — active execution: strategy evaluation, trade lifecycle, NiceGUI dashboard

---

## How It Works

### Strategy: Volatility Trap

Ritrade monitors live trade data from Binance and identifies authentic momentum from the trade stream itself, not from a fixed candle timestamp. The monitor keeps a rolling 10-second diagnostic view and starts a setup window when live activity first becomes qualified.

**Current signal flow:**

```
Each trade updates rolling 10s metrics
        ↓
Monitor checks volume, trade count, and std_dev against calibrated thresholds
        ↓
Rolling window transitions into qualified activity
        ↓
Start a 20s setup qualification window
        ↓
Accumulate trades only for that setup window
        ↓
When the setup window completes, finalize one setup snapshot → Redis
        ↓
Execution layer reads signal state and manages trade lifecycle
```

### Signal Authenticity

The monitor distinguishes real momentum from noise:

| Condition | Meaning | Action |
|---|---|---|
| High std_dev + high trade frequency | Real momentum | Start or strengthen a setup candidate |
| High std_dev + low trade frequency | Manipulated / fake | Skip |
| Low std_dev + steady frequency | Calm market | Skip |

### Activity Score

A 0–1 score computed as the average of three normalized values (volume, std_dev, trade_count), each banded at the calibrated min/max threshold range per ticker.

In the current monitor:
- rolling snapshots are produced continuously from the latest 10-second window
- a setup begins when rolling activity transitions from unqualified to qualified
- the finalized setup snapshot summarizes the intended 20-second setup window only
- the first trade after that window can trigger finalization, but does not extend the summarized setup window

---

## Architecture

### Data Flow

```
market_data/run_trade_ingestion.py  →  Redis ({ticker}_trade_events)  →  monitor/activity_monitor.py
market_data/run_kline_ingestion.py  →  Redis ({ticker}_kline_events)  →  future shared consumers
                                                                    └→  {ticker}_event_channel compatibility for execute
monitor/activity_monitor.py         →  Redis snapshot keys           →  monitor/app.py / execute dashboards
```

### Redis Keys

| Key | Written by | Read by | Content |
|---|---|---|---|
| `rolling_metrics_logs` | `activity_monitor.py` | `monitor/app.py` tab 1 | Rolling 10s window metrics |
| `trap_logs` | `activity_monitor.py` | `monitor/app.py` tab 2 | Finalized setup snapshots from the 20s qualification window |
| `minute_logs` | `activity_monitor.py` | `monitor/app.py` tab 3 | Per-minute summaries |
| `{ticker}_activity_snapshots` | `activity_monitor.py` | `trade/dashboard.py` signals table | Per-ticker finalized setup snapshots |
| `{ticker}_trade_events` | `market_data/run_trade_ingestion.py` | `monitor/activity_monitor.py` | Normalized trade event stream |
| `{ticker}_kline_events` | `market_data/run_kline_ingestion.py` | future consumers | Normalized kline event stream |
| `{ticker}_status` | `services/trade.py` (hset) | `trade/dashboard.py` pinned panels | Full trade state: price, P&L, SL, TP, decisions |
| `{ticker}_event_channel` | `market_data/run_trade_ingestion.py` | `services/trade.py` (sub) | Trade-derived live price ticks via Pub/Sub |
| `execution_commands` | `trade/dashboard.py` (pub) | `breakout/main.py` (sub) | JSON commands: pin, order, cancel, close |
| `execution_pinned_tickers` | `breakout/main.py` (sadd/srem) | `breakout/main.py` (smembers) | Set of pinned tickers, persisted across restarts |

### Logged Data

You can inspect the data saved in Redis directly from the terminal.

List available keys:

```bash
redis-cli KEYS '*'
```

Read the global monitor logs:

```bash
redis-cli GET rolling_metrics_logs
redis-cli GET trap_logs
redis-cli GET minute_logs
```

Read per-ticker saved data, for example `btcusdc`:

```bash
redis-cli GET btcusdc_activity_snapshots
redis-cli GET btcusdc_rolling_metrics_logs
redis-cli GET btcusdc_minute_logs
```

Watch live incoming trade events for a ticker:

```bash
redis-cli SUBSCRIBE btcusdc_trade_events
```

Watch all Redis commands in real time:

```bash
redis-cli MONITOR
```

Pretty-print JSON output when `jq` is installed:

```bash
redis-cli --raw GET rolling_metrics_logs | jq
redis-cli --raw GET btcusdc_rolling_metrics_logs | jq
```

### Execute Layer Flow

```
execute/breakout/main.py  →  ExecutionController
  ├── loads tickers_config.json            — list of supported tickers
  ├── subscribes to execution_commands     — pin/unpin, place/cancel/close orders
  ├── restores execution_pinned_tickers    — persisted pinned set across restarts
  └── per pinned ticker:
        ├── Kline (services/kline.py)      — optional candle stream for future chart / macro consumers
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

- **Rolling window (10s)** — continuous diagnostics used for live monitoring and trigger detection
- **Setup qualification window (20s)** — starts when rolling activity becomes qualified and is used to build one finalized setup snapshot
- **Minute rollover summary** — emitted on minute change for a coarse overview, but not used as the primary strategy anchor
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
├── market_data/                    # Shared market-data ingestion layer
│   ├── models.py                   # TradeEvent + KlineEvent normalized models
│   ├── channels.py                 # Redis channel/key naming helpers
│   ├── storage.py                  # Optional persistence hook interface
│   ├── sources/binance.py          # Binance trade/kline websocket sources
│   ├── publishers/redis.py         # RedisMarketDataPublisher
│   ├── run_trade_ingestion.py      # Trade ingestion entry point
│   └── run_kline_ingestion.py      # Kline ingestion entry point
│
├── monitor/                        # Passive observation layer
│   ├── activity_monitor.py         # Core signal engine — consumes normalized trade events from Redis
│   ├── candle.py                   # Older bucket-based engine (kept for reference, not used in live flow)
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
▶  market_data.run_trade_ingestion  (pid 12345)
▶  monitor/activity_monitor.py      (pid 12346)
▶  monitor/app.py                   (pid 12347)
▶  execute.breakout.main            (pid 12348)
▶  execute.trade.dashboard          (pid 12349)

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

### Run the ingestion services directly

```bash
python -m market_data.run_trade_ingestion
python -m market_data.run_kline_ingestion
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

NiceGUI app. Read-only signal observer. It shows:
- summary cards for current monitor state
- per-ticker snapshot cards with live price, rolling score, latest setup, and minute summary
- three feed tabs for rolling diagnostics, finalized setups, and minute summaries

| Tab | Redis Key | Content |
|---|---|---|
| Rolling 10s Diagnostics | `rolling_metrics_logs` | Rolling 10s window metrics |
| Finalized Setup Snapshots | `trap_logs` | Finalized setup-window summaries with trigger and timing metadata |
| 1-Minute Summary | `minute_logs` | Per-minute trade count, volume, buy/sell breakdown |

### Execution Dashboard (`execute/trade/dashboard.py`) — port 8080

Interactive execution surface. Two sections:

**Pinned Tickers** — one card per pinned ticker:
- Live Price, Floating P&L, Zone, Entry, Stop, Target
- Buy (long limit), Sell (short limit), Trail, Close buttons

**Monitoring Snapshots** — tabbed feed from monitor:
- Finalized setup snapshots: per-ticker activity score, qualified status, trades, volume, WAP, slope
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

1. **Signal semantics polish**: the current rolling `activity_score` is still qualification-gated, so non-qualified windows often show `0.0`; a future enhancement could expose a continuous pre-qualification build-up score.
2. **strategy.py wiring**: `execute/breakout/strategy.py` (`volatility_breakout`) is not currently called — wiring it into `ExecutionController.start_kline` would enable automated breakout detection per ticker.

---

## Infrastructure

- **Binance WebSocket** — live trade stream (`@trade`) and kline stream (`@kline_1m`)
- **Redis** — in-memory message bus shared between monitor and execute layers (port 6379)
- **NiceGUI** — both monitor and execution dashboards
