# Trade Execution Flow

End-to-end execution flow of the `Ritrade` trading system, centered around `ExecutionController`, `Trade`, and the modular strategy layer.

## Overview

1. **Commands:** The dashboard publishes JSON commands to `execution_commands`. `ExecutionController` consumes them and routes to the relevant `Trade` instance.
2. **Strategy evaluation:** Entry and exit logic is delegated to `EntryStrategy` / `ExitStrategy` implementations. The `Trade` class never contains strategy logic directly.
3. **Control mode:** If `control_mode='manual'`, strategy decisions are stored as recommendations but not acted on — the human confirms via the dashboard. If `'automated'`, decisions execute immediately.
4. **Price monitoring:** Each `Trade` runs a background thread (`listen_price_updates`) subscribed to `{ticker}_event_channel`. Trade-derived price ticks trigger entry fill checks and exit evaluation.
5. **State actuation:** `ExecutionService` applies state changes to `TradeState`. `PnLCalculator.build_status()` serializes the result to the `{ticker}_status` Redis hash for the dashboard to read.

---

## Sequence Diagram

```mermaid
sequenceDiagram
    participant UI as Dashboard (UI)
    participant EC as ExecutionController
    participant T as Trade
    participant EK as Kline (Service)
    participant ES_Entry as EntryStrategy
    participant ES_Exit as ExitStrategy
    participant ExS as ExecutionService
    participant PnL as PnLCalculator
    participant Redis as Redis

    %% 1. Command routing
    UI->>Redis: Publish command (e.g. 'place_limit_order')
    Redis->>EC: get_message() via 'execution_commands'
    EC->>EC: handle_command()

    %% 2. Entry request
    EC->>T: submit_entry(position_type, limit_price, initiated_by, control_mode)
    T->>ES_Entry: evaluate_manual_entry(intent, state, snapshot)
    ES_Entry-->>T: EntryDecision (is_valid, entry_price, initial_stop_price)

    alt is_valid == True
        T->>T: state.lifecycle_state = 'pending_entry'
        T->>T: state.limit_price, stop_price set
        T->>Redis: write_status() → {ticker}_status
        TI-->>Redis: Publish trade-derived 'live_price' → {ticker}_event_channel
    end

    %% 3. Price loop
    loop Every Price Tick
        Redis->>T: listen_price_updates() receives live_price
        T->>T: handle_live_price(current_price)

        %% Pending fill check
        T->>ES_Entry: evaluate_pending_entry(state, snapshot)
        ES_Entry-->>T: EntryDecision (action='keep_pending' | 'open_long' | 'open_short')

        alt control_mode == 'automated' AND action == 'open_long'|'open_short'
            T->>ExS: open_position(state, entry_price, stop_price)
            ExS-->>T: state.lifecycle_state = 'open'
            T->>PnL: derive_levels() → target_price
        else control_mode == 'manual'
            T->>T: store recommendation in strategy_state only
        end

        %% Exit evaluation
        T->>ES_Exit: evaluate(state, snapshot)
        ES_Exit-->>T: ExitDecision (action='hold' | 'move_stop' | 'exit_now')

        alt control_mode == 'automated' AND action == 'move_stop'
            T->>ExS: modify_stop(state, stop_price)
        else control_mode == 'automated' AND action == 'exit_now'
            T->>ExS: close_position(state, reason)
        else control_mode == 'manual'
            T->>T: store recommendation in strategy_state only
        end

        T->>PnL: build_status(state, last_update)
        T->>Redis: write_status() → {ticker}_status
    end

    %% 4. Manual override
    UI->>Redis: Publish 'modify_stop' | 'close_position'
    Redis->>EC: get_message()
    EC->>T: modify_stop(stop_price) | close_position()
    T->>T: take_manual_control() — sets control_mode='manual'
    T->>ExS: modify_stop() | close_position()
    T->>Redis: write_status()
```

---

## Key Classes & Methods

### `ExecutionController` (`execute/breakout/main.py`)

- **`run()`** — subscribes to `execution_commands` and polls for incoming commands
- **`handle_command(command)`** — routes commands (`pin_ticker`, `unpin_ticker`, `place_limit_order`, `cancel_order`, `close_position`, `modify_stop`) to the ticker's `Trade` object
- **`get_trade(ticker)`** — lazily creates a `Trade` with injected `ManualEntryStrategy` + `FixedStopExitStrategy`

### `Trade` (`execute/services/trade.py`)

Core orchestrator for a single ticker's runtime.

- **`start()`** — begins the price listener thread and publishes initial status
- **`listen_price_updates()`** — daemon thread subscribed to `{ticker}_event_channel`; routes ticks to `handle_live_price()`
- **`submit_entry(position_type, limit_price, *, initiated_by, control_mode)`** — validates via `EntryStrategy.evaluate_manual_entry()`, transitions to `pending_entry`
- **`handle_live_price(price)`** — heartbeat: triggers `evaluate_pending_entry()` + `evaluate_exit()` + `write_status()`
- **`evaluate_pending_entry(snapshot)`** — delegates fill check to `EntryStrategy`; in automated mode calls `open_position()` on fill
- **`evaluate_exit(snapshot)`** — delegates stop/target check to `ExitStrategy`; in automated mode calls `ExecutionService` to act
- **`take_manual_control()`** / **`release_manual_control()`** — switch `control_mode`; all manual dashboard actions seize control automatically
- **`write_status()`** — serializes current `TradeState` via `PnLCalculator.build_status()` into `{ticker}_status` hash

### `TradeState` (`execute/models/trade_runtime.py`)

Pydantic model holding all runtime state for one ticker.

Key fields: `lifecycle_state`, `control_mode`, `initiated_by`, `manual_override_active`, `strategy_state`, `entry_decision`, `exit_decision`, `decision_reason`, `limit_price`, `entry_price`, `stop_price`, `target_price`, `pnl`, `zone`.

`strategy_state` dict holds: `stop_mode`, and when in manual control, `entry_recommendation` / `exit_recommendation` dicts from the strategies.

### `ExecutionService` (`execute/services/execution.py`)

Thin actuator — isolates `TradeState` mutation from strategy and lifecycle logic.

- **`open_position(state, entry_price, stop_price)`** — sets `lifecycle_state='open'`, locks in `entry_price`
- **`close_position(state, reason)`** — sets `lifecycle_state='closed'`, clears limit
- **`modify_stop(state, stop_price, reason)`** — updates `stop_price`

### Strategy Interfaces (`execute/strategy/base.py`)

- **`EntryStrategy`** — `evaluate_manual_entry(intent, state, snapshot)` + `evaluate_pending_entry(state, snapshot)` → `EntryDecision`
- **`ExitStrategy`** — `evaluate(state, snapshot)` → `ExitDecision`

**Implementations:**

| Class | File | Logic |
|---|---|---|
| `ManualEntryStrategy` | `strategy/manual_entry.py` | Validates entry against `TradeState`; derives stop/target via `PnLCalculator`; checks if price has crossed the limit on pending fill |
| `FixedStopExitStrategy` | `strategy/fixed_stop.py` | Returns `exit_now` when price crosses `stop_price`; `hold` otherwise |

### `PnLCalculator` (`execute/services/pnl_calculator.py`)

Pure math — no side effects.

- **`derive_levels(...)`** — computes `stop_price` and `target_price` from entry price + risk/reward %
- **`calculate_floating_pnl(...)`** — floating P&L in quote currency
- **`build_status(state, last_update)`** — builds `PriceLevels` model for Redis serialization

### Shared Kline Feed (`market_data/run_kline_ingestion.py`)

- Owns Binance `@kline` ingestion for the whole system
- Publishes normalized candles to Redis as `{ticker}_kline_events`
- Any execution strategy that needs candles should subscribe to that shared feed instead of creating its own socket
