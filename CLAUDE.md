# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ritrade is an automated cryptocurrency trading system split into two codebases:

- **`monitor/`** — passive observation layer: signal generation from normalized Redis events, NiceGUI dashboard
- **`market_data/`** — shared ingestion layer: Binance websocket retrieval, normalization, Redis publishing
- **`execute/`** — active execution layer: strategy evaluation, trade lifecycle, NiceGUI dashboard

Both codebases communicate via Redis. The monitor writes signals; the execute layer reads them and acts.

Shared utilities live in **`core_utils/`** at the repo root and are imported by both layers.

## Environment Setup

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Redis must be running locally on port 6379 before starting any process.

## Running the System

### Market Data (run from repo root)

```bash
python -m market_data.run_trade_ingestion  # shared Binance @trade ingestion — writes normalized trade events to Redis
python -m market_data.run_kline_ingestion  # shared Binance @kline ingestion scaffold — writes normalized kline events to Redis
```

### Monitor (run from `monitor/`)

```bash
cd monitor

python activity_monitor.py          # core signal engine — consumes normalized trade events and writes monitoring snapshots
python app.py                       # NiceGUI monitor dashboard — reads from Redis (port 8081)

python volume_spike.py         # optional: volume spike audio alerts for BTC/ETH/SOL/BNB
python volatility.py           # optional: score top 20 pairs, write top 5 to volatile_tickers.txt
```

### Execute (run from **repo root**)

```bash
python -m execute.breakout.main      # execution controller — multi-ticker trade lifecycle
python -m execute.trade.dashboard    # NiceGUI dashboard — pinned ticker controls + signal table (port 8080)
```

> Execute scripts use package-style imports (`execute.breakout.*`, `execute.trade.*`, `core_utils.*`) and must be run as modules from the repo root (`python -m`). Monitor scripts must be run from within `monitor/`.

## Architecture

### Codebase Separation

```
market_data/run_trade_ingestion.py  →  Redis ({ticker}_trade_events)           →  monitor/activity_monitor.py
market_data/run_trade_ingestion.py  →  Redis ({ticker}_event_channel)          →  execute/services/trade.py (live price)
market_data/run_trade_ingestion.py  →  Redis ({ticker}_latest_trade_event)     →  monitor/app.py (per-ticker latest trade)
monitor/activity_monitor.py         →  Redis ({ticker}_activity_snapshots)     →  execute/trade/dashboard.py (signals table)
monitor/activity_monitor.py         →  Redis (monitor_dashboard_updates) pub   →  monitor/app.py (push refresh)
execute/breakout/main.py            →  Redis ({ticker}_status)                 →  execute/trade/dashboard.py (pinned panels)
execute/services/trade.py           →  Redis (execution_dashboard_updates) pub →  execute/trade/dashboard.py (push refresh)
execute/trade/dashboard.py          →  Redis (execution_commands)              →  execute/breakout/main.py (commands)
```

### Shared Utilities (`core_utils/`)

Lives at the repo root; used by both monitor and execute layers.

- `core_utils/format.py` — `format_timestamp(ms)` helper used by `execute/services/trade.py`
- `core_utils/logger/log.py` — shared timestamped logger used by `monitor/volume_spike.py` and `monitor/prices.py`
- `core_utils/tones/` — audio files for macOS `afplay` alerts

### Market Data (`market_data/`)

```
market_data/
  channels.py       — Redis channel/key name constants and helper functions
                       (trade_events_channel, kline_events_channel, execution_price_channel,
                        latest_trade_event_key, latest_kline_event_key, activity_snapshots_key,
                        minute_logs_key, rolling_metrics_key)
                       Global channels: MONITOR_DASHBOARD_UPDATES_CHANNEL,
                                        EXECUTION_DASHBOARD_UPDATES_CHANNEL,
                                        MARKET_DATA_UPDATES_CHANNEL
  models.py         — TradeEvent, KlineEvent Pydantic models
  storage.py        — StorageSink interface + MarketDataEvent type
  publishers/
    redis.py        — RedisMarketDataPublisher
                       publish_trade(): publishes to trade_events_channel, execution_price_channel,
                         MARKET_DATA_UPDATES_CHANNEL, and optionally writes latest_trade_event_key snapshot
                       publish_kline(): publishes to kline_events_channel, optionally writes latest_kline_event_key
                       write_latest_snapshot=True flag enables snapshot storage
  sources/
    binance.py      — BinanceTradeWebSocketSource, BinanceKlineWebSocketSource
    base.py         — WebSocket source base class
  run_trade_ingestion.py  — loads tickers from tickers_config.json, starts one BinanceTradeWebSocketSource per ticker
  run_kline_ingestion.py  — kline ingestion scaffold (same pattern)
```

### Monitor Codebase (`monitor/`)

#### Core Engine (`activity_monitor.py`)

- Loads ticker configs from `tickers_config.json` (multi-ticker support)
- Subscribes to normalized Redis trade-event channels (`{ticker}_trade_events`) — one coroutine per ticker
- Maintains a rolling `ROLLING_WINDOW_MS` (10 s) window of trades, trimming old entries on every tick
- On every trade tick, computes a rolling `ActivitySnapshot` and checks for a **rising-edge qualification**: when the rolling snapshot transitions from `is_qualified_activity = False` → `True`, a setup begins
- Accumulates all trades into a per-ticker setup buffer (`active_setup_trades`) from the qualifying tick onward
- After `QUALIFICATION_WINDOW_MS` (20 s) from the setup start, finalizes a **setup snapshot** from the full buffer, stamped with `setup_start_time`, `setup_end_time`, `qualification_duration_ms`, and `trigger_reason`
- Qualification check: volume, trade count, and std_dev must all fall within calibrated thresholds
- `activity_score` (0–1): average of three normalized values (volume, std_dev, trade_count) using 20th–80th percentile banding
- Writes Redis keys: `trap_logs`, `minute_logs`, `rolling_metrics_logs` (global) and `{ticker}_activity_snapshots`, `{ticker}_rolling_metrics_logs`, `{ticker}_minute_logs` (per-ticker)
- Publishes `monitor_dashboard_updates` Pub/Sub event after each state write to trigger push refresh in `app.py`

`activity_monitor.py` is the **active engine**. `candle.py` is the older bucket-based version — both are kept, but `activity_monitor.py` is the current implementation. Do not confuse them.

#### Calibrated Thresholds

The thresholds in `tickers_config.json` are ticker-specific and were derived from baseline data collection. The archived `tickerstat.py` was used to generate the `.csv` baseline files. Adding a new ticker requires calibrating its thresholds and adding an entry to `tickers_config.json`.

#### Redis Keys (written by monitor)

| Key | Written by | Read by | Content |
|---|---|---|---|
| `trap_logs` | `activity_monitor.py` | `app.py` Setup tab | qualification-triggered setup snapshots (global, all tickers) |
| `minute_logs` | `activity_monitor.py` | `app.py` Minute tab | per-minute summaries (global, all tickers) |
| `rolling_metrics_logs` | `activity_monitor.py` | `app.py` Rolling tab | rolling 10s metrics (global, all tickers) |
| `{ticker}_activity_snapshots` | `activity_monitor.py` | `execute/trade/dashboard.py` | per-ticker finalized setup snapshots |
| `{ticker}_minute_logs` | `activity_monitor.py` | `execute/trade/dashboard.py` | per-ticker minute summaries |
| `{ticker}_rolling_metrics_logs` | `activity_monitor.py` | `app.py` per-ticker cards | per-ticker rolling metrics |
| `{ticker}_trade_events` | `market_data/run_trade_ingestion.py` | `activity_monitor.py` | normalized trade events (Pub/Sub) |
| `{ticker}_latest_trade_event` | `market_data/run_trade_ingestion.py` | `monitor/app.py` | latest trade snapshot (Redis key, not Pub/Sub) |
| `{ticker}_kline_events` | `market_data/run_kline_ingestion.py` | future consumers | normalized kline events |

#### Monitor Dashboard (`app.py`)

NiceGUI app running on port 8081. Push-based refresh via `DashboardPushSubscriber` listening on `monitor_dashboard_updates` and `market_data_updates` channels.

Layout:
- **Summary metrics** — tracked tickers count, qualified-now count, latest setup time
- **Per-Ticker Snapshot cards** — one card per ticker: live price, score, trades, volume; rolling/setup/minute detail lines
- **Monitor Feeds** (three tabs):
  - **Rolling 10s Diagnostics** — global rolling metrics (`rolling_metrics_logs`)
  - **Finalized Setup Snapshots** — qualification-triggered setup data (`trap_logs`)
  - **Minute Rollover Summary** — per-minute candle summaries (`minute_logs`)

#### Supporting Modules

- `signal_score.py` — standalone scoring utility (not yet integrated into live engine); computes a 0–100 signal score from buy/sell volume ratio, momentum, and spread
- `volume_spike.py` — independent WebSocket monitor; uses `core_utils/logger/log.py` for timestamped logging and `afplay` for macOS audio alerts
- `volatility.py` — pre-trade ticker selection; scores top 20 USDT pairs and saves results to `volatile_tickers.txt`
- `prices.py` — early prototype for average price at 20s mark; superseded by `activity_monitor.py`

#### Research (`monitor/research/`)

- `tickerstat.py` — archived baseline data collector; generated the `.csv` files
- `thresh.ipynb` — threshold calibration notebook
- `btcusdc_baseline_*.csv`, `btcusdt_baseline_*.csv`, etc. — baseline data used to calibrate thresholds
- `utils/target.py`, `utils/vbout.py` — research utilities
- `volatile_tickers.txt` — output of `volatility.py`

### Execute Codebase (`execute/`)

#### Execution Flow

```
execute/breakout/main.py  →  ExecutionController
  ├── loads tickers_config.json                    — list of supported tickers
  ├── subscribes to execution_commands             — pin/unpin tickers, orders, stop management
  ├── restores execution_pinned_tickers            — persisted pinned set across restarts
  └── per pinned ticker:
        └── Trade (services/trade.py)
              ├── TradeState (models/trade_runtime.py)  — full lifecycle state machine
              │     idle → pending_entry → open → closed
              ├── EntryStrategy (strategy/manual_entry.py)
              │     evaluate_manual_entry()   — validate entry intent, compute initial stop
              │     evaluate_pending_entry()  — auto-fill when price crosses limit_price
              ├── ExitStrategy (strategy/fixed_stop.py)
              │     evaluate()               — check stop hit, emit exit_now or hold
              ├── ExecutionService (services/execution.py)
              │     open_position / close_position / modify_stop  — apply state changes
              ├── PnLCalculator (services/pnl_calculator.py)
              │     derive_levels()  — stop/target math from entry price
              │     build_status()   — floating P&L and zone per tick
              └── subscribes to {ticker}_event_channel for live price updates (Pub/Sub)
```

#### Package Layout (`execute/`)

```
execute/
  models/               — pure data shapes (Pydantic BaseModel)
    trade_config.py     TradeConfig
    candle.py           Candle
    breakout_log.py     BreakoutLog
    price_status.py     PriceLevels  (output of PnLCalculator.build_status)
    trade_runtime.py    TradeState, MarketSnapshot, ManualEntryIntent,
                        EntryDecision, ExitDecision
                        TradeLifecycle / TradeControlMode / PositionSide type aliases

  services/             — behaviour / orchestration
    pnl_calculator.py   PnLCalculator  (stop/target/P&L math; returns PriceLevels)
    trade.py            Trade          (thread + Redis sub + strategy routing + lifecycle)
    execution.py        ExecutionService  (thin actuator: open/close/modify_stop state changes)

  strategy/             — pluggable strategy implementations
    base.py             EntryStrategy, ExitStrategy ABCs
    manual_entry.py     ManualEntryStrategy  (validates intent, computes stop, handles pending fill)
    fixed_stop.py       FixedStopExitStrategy  (holds until stop hit)

  breakout/
    main.py             ExecutionController entry point
    strategy.py         volatility_breakout function (not currently wired into main.py)

  trade/
    dashboard.py        NiceGUI dashboard (port 8080)
    dashboard.css       styles

  smc/
    smc.py / smcplot.py  research prototypes
```

#### Ticker Configuration (`tickers_config.json`)

Repo-root JSON file listing supported tickers with their calibrated thresholds. `ExecutionController`, `ActivityMonitor`, and both dashboards load from this file.

```json
[
  { "ticker": "BTCUSDC", "min_volume_threshold": ..., "max_volume_threshold": ...,
    "min_trade_count": ..., "max_trade_count": ..., "min_std_dev": ..., "max_std_dev": ... },
  { "ticker": "SOLUSDC", ... }
]
```

#### Trade Lifecycle and Control Modes

`TradeState.lifecycle_state`: `idle` → `pending_entry` → `open` → `closed`

`TradeState.control_mode`: `manual` | `automated`
- In `manual` mode, strategy evaluations produce recommendations stored in `strategy_state` but do not execute automatically
- In `automated` mode, strategy decisions are acted on immediately (auto-fill, auto-exit)
- `manual_override_active` flag tracks whether manual control has been seized during an active trade
- `release_manual_control` command hands the trade back to automated control

#### Redis Keys (written by execute)

| Key | Written by | Read by | Content |
|---|---|---|---|
| `{ticker}_status` | `services/trade.py` (hset) | `trade/dashboard.py` | full trade state: is_pinned, lifecycle_state, position, prices, P&L, quantity, risk/reward, strategy info |
| `{ticker}_event_channel` | `market_data/run_trade_ingestion.py` (pub) | `services/trade.py` (sub) | trade-derived live price ticks; also `shutdown_listener` sentinel |
| `execution_commands` | `trade/dashboard.py` (pub) | `breakout/main.py` (sub) | JSON commands (see below) |
| `execution_pinned_tickers` | `breakout/main.py` (sadd/srem) | `breakout/main.py` (smembers on startup) | set of currently pinned tickers; persisted across restarts |
| `execution_dashboard_updates` | `services/trade.py` (pub) | `trade/dashboard.py` (sub) | push refresh events for the execution dashboard |
| `breakout_logs` | `breakout/strategy.py` | — (not currently read by dashboard) | per-candle breakout signal log |

#### Execution Commands (`execution_commands` channel)

| Action | Required fields | Optional fields | Effect |
|---|---|---|---|
| `pin_ticker` | `ticker` | — | Start trade thread, add to pinned set |
| `unpin_ticker` | `ticker` | — | Stop trade thread, remove from pinned set (blocked if trade active) |
| `place_limit_order` | `ticker`, `side` | `limit_price`, `initiated_by`, `control_mode` | Submit entry via entry strategy |
| `cancel_order` | `ticker` | — | Cancel pending entry, return to idle |
| `close_position` | `ticker` | — | Close open position under manual control |
| `modify_stop` | `ticker`, `stop_price` | — | Update stop price, seize manual control |
| `release_manual_control` | `ticker` | — | Hand active trade back to automated control |

#### NiceGUI Dashboard (`execute/trade/dashboard.py`)

Execution control surface. Runs standalone (`python -m execute.trade.dashboard`). Push-based refresh via `DashboardPushSubscriber` on `execution_dashboard_updates` channel.

**Pinned Tickers** — one card per pinned ticker:
- Header: ticker name, lifecycle state, control mode (MANUAL/AUTOMATED), HOT/WATCH badge (based on qualified status)
- Stats: Live Price, P&L, Entry, Stop, Score
- Buttons: Buy (long limit at live price), Sell (short limit), Trail (trailing stop nudge at 0.15%), Close (close position)
- Footer: zone, last update timestamp

**Monitoring Snapshots** (two tabs):
- **20s Snapshots** — one row per ticker sorted by activity_score desc; shows Score, Qualified, Trades, Volume, WAP, Slope, Pin/Unpin button
- **1m Signal Snapshots** — minute summary rows; shows 1m time, Trades, Volume, Avg Price, 20s Score, Signal, Pin/Unpin button

Score colour-coding: ≥0.6 hot, ≥0.3 warm, else cold

#### SMC Research (`execute/smc/`)

- `smc.py` — standalone SMC/RIMC detection research prototype (not integrated into main.py)
- `smcplot.py` — incomplete Matplotlib plot extraction from smc.py (work in progress)

#### Next Integration Points

1. **strategy.py wiring**: `execute/breakout/strategy.py` (`volatility_breakout`) is not currently called. If reintroduced, it should consume shared `{ticker}_kline_events` from `market_data`, not create its own execution-owned kline feed.

2. **Automated entry**: `control_mode='automated'` is supported in `Trade` — the entry strategy can auto-fill when price crosses limit_price, and the exit strategy can auto-exit on stop hit. Wiring automated entry triggers from monitor signals is a future integration point.

## Other Directories

- **`archive/`** — `candle_old.py`: older bucket-based candle engine (superseded by `activity_monitor.py`)
- **`simulations/`** — `bracketing_income.py`: standalone income/bracketing simulation scripts

## Key Conventions

- `active_setup_*` fields — per-ticker state tracking an in-progress qualification setup (start time, trades buffer, trigger reason); cleared once the finalized snapshot is emitted
- `last_trigger_qualified` — edge-detector flag; setup only starts on a `False → True` transition of `is_qualified_activity`
- `ROLLING_WINDOW_MS` / `QUALIFICATION_WINDOW_MS` — constants governing the rolling trade window (10 s) and the setup collection window (20 s)
- WAP (weighted average price) is used instead of simple average throughout
- `strategy_state` dict on `TradeState` — carries stop_mode (`initial` / `breakeven` / `tightened` / `trailing`), entry/exit recommendations when in manual mode
- Both dashboards are push-based: they subscribe to a Redis Pub/Sub channel and call `.refresh()` on relevant `@ui.refreshable` sections when events arrive (no polling timer)
