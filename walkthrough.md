# Ritrade Codebase Walkthrough

This walkthrough explains the architecture, strategy, and key components of the **Ritrade** project — an automated cryptocurrency trading system using a **volatility trap strategy** on 1-minute candles.

The system is split into two independent layers:
- **`monitor/`** — passive observation, signal generation, Redis publishing
- **`execute/`** — active trade execution, strategy evaluation, lifecycle management

Both layers communicate exclusively through Redis. Neither imports from the other.

---

## 1. Core Strategy: Volatility Trap

The monitor watches the live Binance trade stream and identifies authentic momentum at the **20-second mark** of each candle. Instead of simple indicators, it examines the micro-structure of trades within a rolling 10-second window.

**What makes a signal authentic?**

| Condition | Meaning | Action |
|---|---|---|
| High std_dev + high trade frequency | Real momentum | Fire trap, compute dynamic_factor |
| High std_dev + low trade frequency | Manipulated / whale trade | Skip |
| Low std_dev + steady frequency | Calm market | Skip |

**dynamic_factor** (0–1): the average of three normalized values — volume, std_dev, trade_count — each clamped to calibrated 20th–80th percentile bounds. Prevents outlier whale trades from distorting the signal.

---

## 2. Architecture

```mermaid
graph TD
    A[Binance WebSocket] -->|@trade stream| B[monitor/activity_monitor.py]
    B -->|rolling metrics| D[Redis]
    B -->|trap snapshots| D
    B -->|minute summaries| D

    D -->|poll| E[monitor/app.py\nNiceGUI port 8081]
    D -->|activity_snapshots| F[execute/trade/dashboard.py\nNiceGUI port 8080]

    G[Binance WebSocket] -->|@kline_1m| H[execute/services/kline.py]
    H -->|live_price pub| D
    D -->|live_price sub| I[execute/services/trade.py]
    I -->|ticker_status hset| D

    F -->|execution_commands pub| D
    D -->|execution_commands sub| J[execute/breakout/main.py]
    J --> I
```

---

## 3. Monitor Layer (`monitor/`)

### Core Engine: `activity_monitor.py`

Connects to the Binance WebSocket `@trade` stream. For each ticker in `tickers_config.json`:

- Maintains a **rolling 10-second window** of trades, trimming stale entries on every tick
- At exactly **20 seconds into each minute** (`event_time % 60000 == 20000`), evaluates the window
- Runs an **authenticity check**: volume, trade count, and std_dev must all fall within calibrated thresholds
- If authentic: computes `dynamic_factor` and fires a trap snapshot to Redis

Three Redis keys are written per cycle:

| Key | Content |
|---|---|
| `rolling_metrics_logs` | Rolling 10s metrics — read by monitor dashboard tab 1 |
| `trap_logs` | 20s trap snapshots — read by monitor dashboard tab 2 |
| `minute_logs` | Per-minute summaries — read by monitor dashboard tab 3 |
| `{ticker}_activity_snapshots` | Per-ticker scored snapshots — read by execute dashboard signals table (pending) |

> **Calibrated thresholds** in `activity_monitor.py` are specific to each ticker. They were derived from baseline data collected via `monitor/research/tickerstat.py`. Changing tickers requires recalibrating these values.

### Monitor Dashboard: `app.py` (port 8081)

NiceGUI app. Read-only. Three tabs displaying data from Redis:

- **Micro Buckets (10s)** — rolling window metrics
- **20s Trap Snapshots** — trap trigger data
- **1-Minute Summary** — per-minute candle summaries

### Supporting Scripts

| File | Purpose |
|---|---|
| `volume_spike.py` | Standalone WebSocket monitor for BTC/ETH/SOL/BNB; plays audio alerts via `afplay` |
| `volatility.py` | Scans top 20 USDT pairs, scores by price change + volume + spread; saves top 5 to `volatile_tickers.txt` |
| `signal_score.py` | Standalone 0–100 scorer (buy/sell ratio 50%, momentum 30%, spread 20%) — not yet integrated |
| `candle.py` | Older bucket-based engine; superseded by `activity_monitor.py`, kept for reference |

---

## 4. Execute Layer (`execute/`)

### Entry Point: `ExecutionController` (`execute/breakout/main.py`)

Manages all pinned tickers. On startup:

1. Loads ticker list from `tickers_config.json`
2. Restores previously pinned tickers from `execution_pinned_tickers` Redis set
3. Subscribes to `execution_commands` channel for incoming dashboard commands
4. Per pinned ticker: starts a `Kline` WebSocket listener and a `Trade` instance

**Commands handled:**

| Command | Action |
|---|---|
| `pin_ticker` | Starts Kline + Trade for the ticker; adds to pinned set |
| `unpin_ticker` | Shuts down Kline + Trade; removes from pinned set |
| `place_limit_order` | Calls `trade.submit_entry()` |
| `cancel_order` | Calls `trade.cancel_order()` |
| `close_position` | Calls `trade.close_position()` |
| `modify_stop` | Calls `trade.modify_stop()` |

### Trade Lifecycle: `Trade` (`execute/services/trade.py`)

The core orchestrator for a single ticker. Holds a `TradeState` and delegates all decisions to strategy objects.

**State machine:**

```
idle  →  pending_entry  →  open  →  closed
```

**Key methods:**

- `submit_entry(position_type, limit_price, *, initiated_by, control_mode)` — validates via `EntryStrategy`, transitions to `pending_entry`
- `handle_live_price(price)` — called on every Redis tick; triggers `evaluate_pending_entry` + `evaluate_exit`
- `evaluate_pending_entry()` — asks `EntryStrategy` if the limit has been hit; if so, calls `open_position()`
- `evaluate_exit()` — asks `ExitStrategy` whether to hold, modify stop, or exit
- `write_status()` — serializes `TradeState` via `PnLCalculator.build_status()` into `{ticker}_status` Redis hash

**Manual vs automated control:**

| `control_mode` | Behaviour |
|---|---|
| `'manual'` | Strategy decisions are stored in `strategy_state` as recommendations; not acted on |
| `'automated'` | Strategy decisions execute immediately (fill, stop hit, exit) |

Any manual dashboard action (modify stop, close) automatically switches `control_mode` to `'manual'`. Use `release_manual_control()` to hand back to automation.

### Runtime Models: `execute/models/trade_runtime.py`

All runtime state is held in a single `TradeState` Pydantic model:

| Field | Type | Purpose |
|---|---|---|
| `lifecycle_state` | `TradeLifecycle` | `idle / pending_entry / open / closed` |
| `control_mode` | `TradeControlMode` | `manual / automated` |
| `initiated_by` | `TradeInitiator` | `manual / automated` |
| `manual_override_active` | `bool` | True when human has taken control |
| `strategy_state` | `dict` | Strategy-specific state: stop_mode, recommendations |
| `entry_decision` / `exit_decision` | `str` | Last decision action taken |

DTOs passed between `Trade` and strategies:
- `MarketSnapshot` — ticker + live_price + timestamp
- `ManualEntryIntent` — side + limit_price + source
- `EntryDecision` — action, is_valid, entry_price, initial_stop_price, reason
- `ExitDecision` — action, stop_price, reason

### Strategy Layer: `execute/strategy/`

Pluggable entry and exit logic behind clean ABCs.

**`EntryStrategy` (ABC):**
- `evaluate_manual_entry(intent, state, snapshot) → EntryDecision`
- `evaluate_pending_entry(state, snapshot) → EntryDecision`

**`ExitStrategy` (ABC):**
- `evaluate(state, snapshot) → ExitDecision`

**Implementations:**

| Class | File | Behaviour |
|---|---|---|
| `ManualEntryStrategy` | `strategy/manual_entry.py` | Validates entry, derives stop/target via `PnLCalculator`, returns `EntryDecision`. Fills limit when price crosses. |
| `FixedStopExitStrategy` | `strategy/fixed_stop.py` | Returns `exit_now` when live price crosses the stop; `hold` otherwise. |

### Execution Service: `ExecutionService` (`execute/services/execution.py`)

Thin actuator that mutates `TradeState` only. Keeps state changes out of the strategy and trade classes.

- `open_position(state, entry_price, stop_price)` — flips lifecycle to `open`
- `close_position(state, reason)` — flips lifecycle to `closed`
- `modify_stop(state, stop_price, reason)` — updates `stop_price`

### PnL Calculator: `PnLCalculator` (`execute/services/pnl_calculator.py`)

Pure math — no Redis, no side effects.

- `derive_levels(entry_price, account_balance, quantity, risk_percent, reward_percent, position_type)` — computes stop and target prices
- `calculate_floating_pnl(position_type, entry_price, current_price, quantity)` — floating P&L in quote currency
- `build_status(state, last_update)` — builds a `PriceLevels` model for Redis serialization

### Kline Service: `Kline` (`execute/services/kline.py`)

- Connects to Binance `@kline_1m` WebSocket per ticker
- Publishes `{"live_price": ...}` to `{ticker}_event_channel` on every tick
- `stop()` sends a `shutdown_listener` sentinel and cancels the asyncio task

### Execution Dashboard: `execute/trade/dashboard.py` (port 8080)

Interactive NiceGUI surface. Refreshes every 1 second via `ui.timer`.

**Pinned Tickers section** — one card per pinned ticker from `execution_pinned_tickers`:
- Stat cards: Live Price, Floating P&L, Zone, Entry, Stop, Score
- Buttons: Buy, Sell, Trail, Close → publish JSON to `execution_commands`

**Monitoring Snapshots section** — tabbed feed:
- **20s Snapshots**: per-ticker activity score, qualified flag, trades, volume, WAP, slope
- **1m Signal Snapshots**: per-minute candle data per ticker
- Rows sorted by `activity_score` descending; positive signals highlighted

---

## 5. Shared Utilities (`core_utils/`)

Used by both monitor and execute layers. Lives at the repo root.

| File | Export | Usage |
|---|---|---|
| `format.py` | `format_timestamp(ms)` | Human-readable timestamp string |
| `logger/log.py` | `log(msg)` | Timestamped console logger |
| `tones/` | `.aiff` / `.wav` files | macOS `afplay` audio alerts |

---

## 6. Typical Execution Flow

1. Start Redis: `brew services start redis`
2. Run `make start` — starts all four processes in the background
3. Open `http://localhost:8080` — execute dashboard
4. Open `http://localhost:8081` — monitor dashboard
5. Pin a ticker from the Signals table in the execute dashboard
6. Use Buy/Sell to place a limit order; watch it fill when price crosses
7. Close manually or let `FixedStopExitStrategy` exit on stop hit (automated mode only)

---

## 7. Testing

Tests live in `tests/` and use a `FakeRedis` stub to avoid a live Redis dependency.

```bash
pytest tests/ -v
```

Key test cases in `test_trade_runtime.py`:
- Manual entry shapes state correctly
- Manual control blocks automated fill (stores recommendation only)
- Automated pending entry fills and opens position
- Open trade closes when stop is hit in automated mode
- Manual command overrides automated control mid-trade
- Redis status hash contains all required dashboard fields
- `PnLCalculator` stop/target/P&L math

---

## 8. Next Integration Points

1. **Monitor → per-ticker snapshots**: `activity_monitor.py` needs to write `{ticker}_activity_snapshots` keys (one per ticker in `tickers_config.json`) so the execute dashboard signals table shows live data.
2. **strategy.py wiring**: `execute/breakout/strategy.py` (`volatility_breakout`) is not currently called — `ExecutionController.start_kline` creates `Kline` with no `on_candle` callback. Wiring it in would enable automated breakout entry per ticker.
