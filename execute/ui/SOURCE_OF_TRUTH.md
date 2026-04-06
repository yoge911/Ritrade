# Execute UI Source Of Truth

This React migration preserves the current NiceGUI execute dashboard behavior from [`execute/trade/dashboard.py`](../trade/dashboard.py).

| NiceGUI source | Redis / pubsub contract | React parity target |
|---|---|---|
| `load_tickers()` | `tickers_config.json` | bridge snapshot builder seed list |
| `load_json()` | `{ticker}_activity_snapshots`, `{ticker}_minute_logs` | bridge Redis readers |
| `load_status()` | `{ticker}_status` | bridge pinned status assembly |
| `pinned_tickers()` | `execution_pinned_tickers` | `PinnedTickersPanel` ordering/input |
| `publish_command()` | `execution_commands` | bridge command POST endpoint |
| `latest_activity_snapshot()` | `{ticker}_activity_snapshots` | pinned cards and snapshot tables |
| `latest_minute_snapshot()` | `{ticker}_minute_logs` | minute snapshot table |
| `latest_signal_rows()` | pinned set + latest activity + latest minute | bridge row assembly |
| `score_class()` | UI rule only | score badge styling |
| `is_positive_signal()` | row payload fields | positive row highlighting and signal label |
| `send_trailing_stop()` | `modify_stop` on `execution_commands` | trail action |
| `handle_order()` | `place_limit_order` on `execution_commands` | buy/sell actions |
| `render_pinned_tickers_section()` | pinned set + `{ticker}_status` + latest activity | `PinnedTickersPanel` / `PinnedTickerCard` |
| `render_activity_snapshots_panel()` | latest signal rows | `ActivitySnapshotsTable` |
| `render_minute_snapshots_panel()` | latest signal rows | `MinuteSnapshotsTable` |
| `DashboardPushSubscriber.listen()` | `execution_dashboard_updates` | bridge Redis subscriber -> `/ws/execute` |
