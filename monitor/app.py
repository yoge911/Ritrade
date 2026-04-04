import json
import os
from datetime import datetime
import redis
from nicegui import ui

# ── Configuration ─────────────────────────────────────────────────────────────

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB   = 0

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

CSS_PATH = os.path.join(os.path.dirname(__file__), 'dashboard.css')

# ── Data loading ──────────────────────────────────────────────────────────────

def load(key: str, limit: int = 60) -> list[dict]:
    """Read a JSON list from Redis, returning at most `limit` entries."""
    return json.loads(redis_client.get(key) or '[]')[:limit]

def make_columns(rows: list[dict]) -> list[dict]:
    """Build NiceGUI table column definitions from the keys of the first row."""
    if not rows:
        return []
    return [{'name': k, 'label': k.upper(), 'field': k, 'align': 'left'} for k in rows[0].keys()]

# ── Page ──────────────────────────────────────────────────────────────────────

@ui.page('/')
def main():
    with open(CSS_PATH) as f:
        ui.add_head_html(f'<style>{f.read()}</style>')

    # ── Header ────────────────────────────────────────────────────────────────
    with ui.element('div').classes('header w-full'):
        with ui.row().classes('items-center gap-0'):
            ui.label('Ritrade').classes('header-title')
            ui.label('Monitor · BTCUSDC').classes('header-subtitle')
        last_updated = ui.label('—').classes('header-timestamp')

    # ── Main content ──────────────────────────────────────────────────────────
    with ui.column().classes('w-full q-pa-lg gap-4'):

        with ui.tabs().props('align=left dense').classes('w-full') as tabs:
            tab_rolling = ui.tab('Micro Buckets (10s)').props('no-caps')
            tab_trap    = ui.tab('20s Trap Snapshots').props('no-caps')
            tab_minute  = ui.tab('1-Minute Summary').props('no-caps')

        with ui.tab_panels(tabs, value=tab_rolling).classes('w-full'):

            with ui.tab_panel(tab_rolling):
                ui.label('10s Rolling Window').classes('section-title')
                rolling_empty = ui.label('Waiting for rolling metrics data…').classes('empty-state')
                rolling_table = ui.table(columns=[], rows=[], row_key='timestamp').classes('data-table w-full')

            with ui.tab_panel(tab_trap):
                ui.label('20s Trap Snapshots').classes('section-title')
                trap_empty = ui.label('Waiting for trap snapshots…').classes('empty-state')
                trap_table = ui.table(columns=[], rows=[], row_key='timestamp').classes('data-table w-full')

            with ui.tab_panel(tab_minute):
                ui.label('1-Minute Candle Summary').classes('section-title')
                minute_empty = ui.label('Waiting for 1-min candle summaries…').classes('empty-state')
                minute_table = ui.table(columns=[], rows=[], row_key='timestamp').classes('data-table w-full')

    # ── Periodic update ───────────────────────────────────────────────────────
    def update_ui():
        rolling = load('rolling_metrics_logs')
        trap    = load('trap_logs')
        minute  = load('minute_logs')

        # Rolling metrics
        rolling_empty.set_visibility(not rolling)
        rolling_table.set_visibility(bool(rolling))
        if rolling:
            rolling_table.columns = make_columns(rolling)
            rolling_table.rows    = rolling
            rolling_table.update()

        # Trap snapshots
        trap_empty.set_visibility(not trap)
        trap_table.set_visibility(bool(trap))
        if trap:
            trap_table.columns = make_columns(trap)
            trap_table.rows    = trap
            trap_table.update()

        # Minute summaries
        minute_empty.set_visibility(not minute)
        minute_table.set_visibility(bool(minute))
        if minute:
            minute_table.columns = make_columns(minute)
            minute_table.rows    = minute
            minute_table.update()

        last_updated.text = f"Updated {datetime.now().strftime('%H:%M:%S')}"

    ui.timer(2.0, update_ui)

# ── Run ───────────────────────────────────────────────────────────────────────

ui.run(title='Ritrade Monitor', dark=True, favicon='📊', port=8081, reload=False)