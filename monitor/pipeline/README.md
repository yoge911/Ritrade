# Monitor Calibration Pipeline

This folder documents how archived trade data becomes calibration thresholds, how one calibration run becomes active for runtime use, and how the monitor UI displays and switches between calibration runs.

## Overview

The calibration and monitor pipeline currently works like this:

1. Trade ingestion writes hourly archive files under `data/trade_archive/...`.
2. The calibration job reads those archive files, samples rolling windows, and computes thresholds for each ticker.
3. Each calibration cycle becomes one immutable calibration run with a stable `run_id`.
4. Calibration storage records:
   - immutable history files in `calibration/history/`
   - an authoritative active/latest pointer in `calibration/active_state.json`
   - a runtime mirror file in `calibration/activity_thresholds.json`
5. The live monitor runtime resolves the active calibration run and reloads those thresholds periodically.
6. The monitor UI shows calibration history, active/latest status, per-run threshold details, and allows explicit activation of a selected run.

Important behavior:

- `latest` means the most recently computed calibration run.
- `active` means the run currently used by the monitor runtime.
- `selected` means the run the user is currently viewing in the monitor UI.
- In `auto` mode, new calibration runs become both `latest` and `active`.
- In `manual` mode, new calibration runs only update `latest`; `active` stays pinned until the user changes it.

## Diagrams

- [calibration_monitor_sequence.md](/Users/yogesh/Documents/Ritrade/monitor/pipeline/calibration_monitor_sequence.md): end-to-end interaction across archive data, calibration job, storage, runtime monitor loading, Redis, and UI.
- [calibration_monitor_activity.md](/Users/yogesh/Documents/Ritrade/monitor/pipeline/calibration_monitor_activity.md): activity-style view of the same process, with method nodes highlighted.

## Method Guide

### Calibration Job

From [`monitor/calibrate_activity.py`](/Users/yogesh/Documents/Ritrade/monitor/calibrate_activity.py)

- `main`: runs the calibration loop on a schedule and records each completed run.
- `run_calibration`: builds one full calibration run across all configured tickers.
- `generate_run_id`: creates the stable run identifier for a calibration cycle.
- `calibrate_ticker`: computes one ticker’s thresholds from archived trade data.
- `load_trade_events`: reads the archive events for a ticker within the requested lookback window.
- `hourly_archive_paths`: determines which hourly archive files must be scanned.
- `sample_window_metrics`: replays archived trades into rolling-window metric samples.
- `build_thresholds`: turns sampled metrics into percentile-based thresholds.
- `validate_thresholds`: ensures the computed threshold set is usable before storing it.

### Calibration Storage

From [`monitor/calibration_store.py`](/Users/yogesh/Documents/Ritrade/monitor/calibration_store.py)

- `record_calibration_run`: writes a new immutable run, updates active/latest state, mirrors the active run for runtime, and prunes history.
- `write_calibration_run`: persists a calibration run into immutable history.
- `list_calibration_runs`: returns all stored calibration runs in newest-first order.
- `load_calibration_run`: loads one historical run by `run_id`.
- `load_active_calibration_state`: reads the authoritative active/latest pointer state.
- `write_active_calibration_state`: atomically writes the active/latest pointer state.
- `resolve_active_calibration_snapshot`: resolves the runtime-effective calibration run, preferring the active pointer over the mirror file.
- `activate_calibration_run`: explicitly promotes a selected historical run to active and switches into manual mode.
- `set_activation_mode`: switches between `auto` and `manual` activation behavior.
- `prune_calibration_history`: removes expired historical runs while preserving the active run.
- `_sync_runtime_snapshot`: mirrors the active historical run into the runtime convenience snapshot.

### Live Monitor Runtime

From [`monitor/activity_monitor.py`](/Users/yogesh/Documents/Ritrade/monitor/activity_monitor.py)

- `load_runtime_configs`: loads ticker thresholds from the active calibration run.
- `refresh_configs_periodically`: reloads thresholds on a fixed cadence so activation changes are picked up without a restart.
- `refresh_configs`: applies the latest loaded thresholds to in-memory ticker states.
- `consume_trade_events`: listens for live normalized trade events from Redis.
- `handle_trade_event`: routes a live event into the right ticker state and persists the resulting monitor data.
- `TickerState.process_trade_event`: updates rolling windows, minute summaries, and setup snapshots for one ticker.
- `generate_activity_snapshot`: builds the rolling metrics snapshot used for live monitoring.
- `generate_setup_snapshot`: builds the finalized setup snapshot once a qualification window completes.
- `save_state_to_redis`: writes monitor outputs to Redis and triggers a UI refresh event.

### Monitor UI

From [`monitor/app.py`](/Users/yogesh/Documents/Ritrade/monitor/app.py)

- `resolve_calibration_view_model`: builds the calibration panel state from history, active pointer data, and current UI selection.
- `render_calibration_panel`: renders the calibration run selector, active/latest state, threshold table, and activation controls.
- `handle_calibration_run_selection`: changes the viewed run without changing the active runtime calibration.
- `handle_calibration_activation`: activates the selected run and notifies the user that runtime updates on the next refresh cycle.
- `handle_activation_mode_change`: switches between `auto` and `manual` activation mode from the UI.
- `build_calibration_option_label`: formats selector entries with `active` and `latest` indicators.
- `calibration_table_rows`: converts a calibration run into per-ticker table rows for display.
- `refresh_monitor_dashboard`: refreshes all dashboard sections after live updates or calibration UI actions.

## Reading The Flow

When you read the diagrams, the simplest way to think about the system is:

- archive files are the historical input
- calibration runs are the computed output
- active state decides what runtime actually uses
- the monitor engine applies the active thresholds to live data
- the UI lets you inspect history and explicitly control activation
