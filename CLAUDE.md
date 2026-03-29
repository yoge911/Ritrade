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

python candle_roll.py          # core signal engine — writes to Redis
streamlit run app.py           # Streamlit dashboard — reads from Redis

python volume_spike.py         # optional: volume spike audio alerts for BTC/ETH/SOL/BNB
python volatility.py           # optional: score top 20 pairs, write top 5 to volatile_tickers.txt
```

### Execute (run from **repo root**)

```bash
python -m execute.breakout.main      # execution engine — Kline feed + strategy + trade monitor
python -m execute.trade.dashboard    # NiceGUI dashboard — live trade status and breakout logs
```

> Execute scripts use package-style imports (`execute.breakout.*`, `execute.trade.*`, `core_utils.*`) and must be run as modules from the repo root (`python -m`). Monitor scripts must be run from within `monitor/`.

## Architecture

### Codebase Separation

```
monitor/candle_roll.py  →  Redis  →  execute/breakout/main.py
                                  →  monitor/app.py (Streamlit, read-only)
                                  →  execute/trade/dashboard.py (NiceGUI, interactive)
```

### Shared Utilities (`core_utils/`)

Lives at the repo root; used by both monitor and execute layers.

- `core_utils/format.py` — `format_timestamp(ms)` helper used by `execute/core/trade.py`
- `core_utils/logger/log.py` — shared timestamped logger used by `monitor/volume_spike.py` and `monitor/prices.py`
- `core_utils/tones/` — audio files for macOS `afplay` alerts

### Monitor Codebase (`monitor/`)

#### Core Engine (`candle_roll.py`)

- Connects to Binance WebSocket (`@trade` stream)
- Maintains a rolling 10-second window of trades, trimming old entries on every tick
- At exactly **20 seconds into each minute** (`event_time % 60000`), fires a trap snapshot
- Authenticity check before firing: volume, trade count, and std_dev must all fall within calibrated thresholds
- Computes `dynamic_factor` (0–1): average of three normalized values (volume, std_dev, trade_count) using 20th–80th percentile banding
- Writes three Redis keys: `trap_logs`, `minute_logs`, `rolling_metrics_logs`

`candle_roll.py` is the **active engine**. `candle.py` is the older bucket-based version — both are kept, but `candle_roll.py` is the current implementation. Do not confuse them.

#### Calibrated Thresholds

The thresholds in `candle_roll.py` (and `candle.py`) are specific to **BTCUSDC** and were derived from baseline data collection. The archived `tickerstat.py` was used to generate the `.csv` baseline files. Changing the ticker requires recalibrating these values.

#### Redis Keys (written by monitor)

| Key | Written by | Read by | Content |
|---|---|---|---|
| `trap_logs` | `candle_roll.py` | `app.py` tab 2, `execute/trade/dashboard.py` | 20s trap snapshots |
| `minute_logs` | `candle_roll.py` | `app.py` tab 3 | per-minute summaries |
| `rolling_metrics_logs` | `candle_roll.py` | `app.py` tab 1 | rolling 10s metrics |

#### Streamlit Dashboard (`app.py`)

Multi-page app. Additional pages live in `pages/` and are auto-loaded by Streamlit:
- `pages/how_it_works.py` — codebase walkthrough
- `pages/vbout_walkthrough.py` — execute/ codebase walkthrough

#### Supporting Modules

- `signal_score.py` — standalone scoring utility (not yet integrated into live engine); computes a 0–100 signal score from buy/sell volume ratio, momentum, and spread
- `volume_spike.py` — independent WebSocket monitor; uses `core_utils/logger/log.py` for timestamped logging and `afplay` for macOS audio alerts
- `volatility.py` — pre-trade ticker selection; scores top 20 USDT pairs and saves results to `volatile_tickers.txt`
- `prices.py` — early prototype for average price at 20s mark; superseded by `candle_roll.py`

#### Research (`monitor/research/`)

- `tickerstat.py` — archived baseline data collector; generated the `.csv` files
- `thresh.ipynb` — threshold calibration notebook
- `btcusdc_baseline_*.csv`, `btcusdt_baseline_*.csv`, etc. — baseline data used to calibrate thresholds
- `utils/target.py`, `utils/vbout.py` — research utilities
- `volatile_tickers.txt` — output of `volatility.py`

### Execute Codebase (`execute/`)

#### Execution Flow

```
execute/breakout/main.py
  ├── Kline (breakout/kline.py)      — WebSocket @kline_1m feed; publishes live_price to Redis Pub/Sub
  ├── strategy.py (breakout/)        — volatility_breakout logic on closed candles → writes breakout_logs to Redis
  └── Trade (trade/trade.py)
        ├── PnL (trade/PnL.py)       — stop/target math and floating P&L per tick
        └── subscribes to Redis Pub/Sub ({ticker}_event_channel) for live price updates from Kline
```

#### Redis Keys (written by execute)

| Key | Written by | Read by | Content |
|---|---|---|---|
| `breakout_logs` | `breakout/strategy.py` | `trade/dashboard.py` | per-candle breakout signal log |
| `{ticker}_status` | `trade/trade.py` (hmset) | `trade/dashboard.py` | live trade status: price, P&L, SL, TP |
| `{ticker}_event_channel` | `breakout/kline.py` (pub) | `trade/trade.py` (sub) | live price ticks via Pub/Sub |

#### NiceGUI Dashboard (`execute/trade/dashboard.py`)

Interactive execution UI with live trade status cards, breakout log table, and Buy/Sell buttons. Runs standalone (`python -m execute.trade.dashboard`).

#### SMC Research (`execute/smc/`)

- `smc.py` — standalone SMC/RIMC detection research prototype (not integrated into main.py)
- `smcplot.py` — incomplete Matplotlib plot extraction from smc.py (work in progress)

#### Missing Link

`execute/breakout/strategy.py` implements a price range breakout. The calibrated **volatility trap** logic from `monitor/candle_roll.py` has not yet been ported into it. This is the next integration point.

## Other Directories

- **`archive/`** — `candle_old.py`: older bucket-based candle engine (superseded by `candle_roll.py`)
- **`simulations/`** — `bracketing_income.py`: standalone income/bracketing simulation scripts

## Key Conventions

- `master_*` variables = accumulated across the full minute
- `bucket_*` variables = scoped to a single time window
- `already_triggered_20s` — guard flag ensuring the trap fires only once per minute
- WAP (weighted average price) is used instead of simple average throughout
