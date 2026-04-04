# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ritrade is an automated cryptocurrency trading system split into two codebases:

- **`monitor/`** — passive observation layer: signal generation, Redis publishing, Streamlit dashboard
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

### Monitor (run from `monitor/`)

```bash
cd monitor

python activity_monitor.py          # core signal engine — writes to Redis
python app.py                  # NiceGUI monitor dashboard — reads from Redis (port 8081)

python volume_spike.py         # optional: volume spike audio alerts for BTC/ETH/SOL/BNB
python volatility.py           # optional: score top 20 pairs, write top 5 to volatile_tickers.txt
```

### Execute (run from **repo root**)

```bash
python -m execute.breakout.main      # execution controller — multi-ticker Kline feeds + trade lifecycle
python -m execute.trade.dashboard    # NiceGUI dashboard — pinned ticker controls + signal table
```

> Execute scripts use package-style imports (`execute.breakout.*`, `execute.trade.*`, `core_utils.*`) and must be run as modules from the repo root (`python -m`). Monitor scripts must be run from within `monitor/`.

## Architecture

### Codebase Separation

```
monitor/activity_monitor.py  →  Redis ({ticker}_activity_snapshots)  →  execute/trade/dashboard.py (signals table)
execute/breakout/main.py     →  Redis ({ticker}_status)              →  execute/trade/dashboard.py (pinned panels)
execute/trade/dashboard.py   →  Redis (execution_commands)           →  execute/breakout/main.py (commands)
```

### Shared Utilities (`core_utils/`)

Lives at the repo root; used by both monitor and execute layers.

- `core_utils/format.py` — `format_timestamp(ms)` helper used by `execute/services/trade.py`
- `core_utils/logger/log.py` — shared timestamped logger used by `monitor/volume_spike.py` and `monitor/prices.py`
- `core_utils/tones/` — audio files for macOS `afplay` alerts

### Monitor Codebase (`monitor/`)

#### Core Engine (`activity_monitor.py`)

- Connects to Binance WebSocket (`@trade` stream)
- Maintains a rolling 10-second window of trades, trimming old entries on every tick
- At exactly **20 seconds into each minute** (`event_time % 60000`), fires a trap snapshot
- Authenticity check before firing: volume, trade count, and std_dev must all fall within calibrated thresholds
- Computes `dynamic_factor` (0–1): average of three normalized values (volume, std_dev, trade_count) using 20th–80th percentile banding
- Writes three Redis keys: `trap_logs`, `minute_logs`, `rolling_metrics_logs`

`activity_monitor.py` is the **active engine**. `candle.py` is the older bucket-based version — both are kept, but `activity_monitor.py` is the current implementation. Do not confuse them.

#### Calibrated Thresholds

The thresholds in `activity_monitor.py` (and `candle.py`) are specific to **BTCUSDC** and were derived from baseline data collection. The archived `tickerstat.py` was used to generate the `.csv` baseline files. Changing the ticker requires recalibrating these values.

#### Redis Keys (written by monitor)

| Key | Written by | Read by | Content |
|---|---|---|---|
| `trap_logs` | `activity_monitor.py` | `app.py` tab 2 | 20s trap snapshots |
| `minute_logs` | `activity_monitor.py` | `app.py` tab 3 | per-minute summaries |
| `rolling_metrics_logs` | `activity_monitor.py` | `app.py` tab 1 | rolling 10s metrics |
| `{ticker}_activity_snapshots` | `activity_monitor.py` (pending) | `execute/trade/dashboard.py` (signals table) | per-ticker activity snapshots |

#### Monitor Dashboard (`app.py`)

NiceGUI app running on port 8081. Three tabs displaying signal data from Redis:
- **Micro Buckets (10s)** — rolling window metrics (`rolling_metrics_logs`)
- **20s Trap Snapshots** — trap trigger data (`trap_logs`)
- **1-Minute Summary** — per-minute candle summaries (`minute_logs`)

Additional Streamlit pages (`pages/`) are kept for reference but are no longer part of the live system.

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
  ├── loads tickers_config.json            — list of supported tickers
  ├── subscribes to execution_commands     — pin/unpin tickers, place/cancel/close orders
  ├── restores execution_pinned_tickers    — persisted pinned set across restarts
  └── per pinned ticker:
        ├── Kline (services/kline.py)      — WebSocket @kline_1m; publishes live_price to {ticker}_event_channel
        └── Trade (services/trade.py)
              ├── state machine: idle → pending_entry → open → closed
              ├── evaluate_fill()          — auto-fills limit order when price crosses limit_price
              ├── PnLCalculator            — stop/target math and floating P&L per tick
              │   (services/pnl_calculator.py)
              └── subscribes to {ticker}_event_channel for live price updates
```

#### Package Layout (`execute/`)

```
execute/
  models/               — pure data shapes (Pydantic BaseModel)
    trade_config.py     TradeConfig
    candle.py           Candle
    breakout_log.py     BreakoutLog
    price_status.py     PriceLevels  (ticker, is_pinned, state, position, prices, pnl, quantity, risk/reward)

  services/             — behaviour / orchestration (plain Python classes)
    kline.py            Kline          (WebSocket + Redis pub; stop() for graceful shutdown)
    pnl_calculator.py   PnLCalculator  (stop/target/P&L math; returns PriceLevels)
    trade.py            Trade          (thread + Redis sub + state machine + limit order lifecycle)

  breakout/
    main.py             ExecutionController entry point
    strategy.py         volatility_breakout function (not currently wired into main.py)

  trade/
    dashboard.py        NiceGUI dashboard
    dashboard.css       styles

  smc/
    smc.py / smcplot.py  research prototypes
```

#### Ticker Configuration (`tickers_config.json`)

Repo-root JSON file listing supported tickers with their calibrated thresholds. `ExecutionController` and the dashboard both load from this file to determine valid tickers.

```json
[
  { "ticker": "BTCUSDC", "min_volume_threshold": ..., "max_volume_threshold": ..., ... },
  { "ticker": "SOLUSDC", ... }
]
```

#### Redis Keys (written by execute)

| Key | Written by | Read by | Content |
|---|---|---|---|
| `{ticker}_status` | `services/trade.py` (hset) | `trade/dashboard.py` | full trade state: is_pinned, state, position, prices, P&L, quantity, risk/reward |
| `{ticker}_event_channel` | `services/kline.py` (pub) | `services/trade.py` (sub) | live price ticks via Pub/Sub; also `shutdown_listener` sentinel |
| `execution_commands` | `trade/dashboard.py` (pub) | `breakout/main.py` (sub) | JSON commands: `pin_ticker`, `unpin_ticker`, `place_limit_order`, `cancel_order`, `close_position` |
| `execution_pinned_tickers` | `breakout/main.py` (sadd/srem) | `breakout/main.py` (smembers on startup) | set of currently pinned tickers; persisted across restarts |
| `breakout_logs` | `breakout/strategy.py` | — (not currently read by dashboard) | per-candle breakout signal log |

#### NiceGUI Dashboard (`execute/trade/dashboard.py`)

Execution control surface. Runs standalone (`python -m execute.trade.dashboard`). Refreshes every 1 second via `ui.timer`.

Two sections:

**Pinned Tickers** — one panel per pinned ticker (from `execution_pinned_tickers`):
- Stat cards: Live Price, Floating P&L, Zone, Entry, Stop, Target (from `{ticker}_status`)
- Buttons: Buy (long limit at current price), Sell (short limit), Cancel (pending order), Close (open position), Unpin
- Commands are sent as JSON to `execution_commands` channel

**Signals** — one row per ticker in `tickers_config.json`, sorted by `activity_score` descending:
- Shows: Trades, Vol, WAP, Std Dev, Slope, activity score, qualified status (from `{ticker}_activity_snapshots`)
- Pin/Unpin button per row; score colour-coded: ≥0.6 hot, ≥0.3 warm, else cold

#### SMC Research (`execute/smc/`)

- `smc.py` — standalone SMC/RIMC detection research prototype (not integrated into main.py)
- `smcplot.py` — incomplete Matplotlib plot extraction from smc.py (work in progress)

#### Next Integration Points

1. **Monitor → per-ticker snapshots**: `monitor/activity_monitor.py` needs to write `{ticker}_activity_snapshots` keys (one per ticker in `tickers_config.json`) so the execute dashboard signals table shows live data. Currently this key is not written.

2. **strategy.py wiring**: `execute/breakout/strategy.py` (`volatility_breakout`) is not currently called — `ExecutionController.start_kline` creates `Kline` with no `on_candle` callback. Wiring it back in would enable automated breakout detection per ticker.

## Other Directories

- **`archive/`** — `candle_old.py`: older bucket-based candle engine (superseded by `activity_monitor.py`)
- **`simulations/`** — `bracketing_income.py`: standalone income/bracketing simulation scripts

## Key Conventions

- `master_*` variables = accumulated across the full minute
- `bucket_*` variables = scoped to a single time window
- `already_triggered_20s` — guard flag ensuring the trap fires only once per minute
- WAP (weighted average price) is used instead of simple average throughout
