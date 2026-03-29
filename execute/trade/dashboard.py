import json
import os
import redis
from nicegui import ui

# ── Configuration ─────────────────────────────────────────────────────────────

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB   = 0

REDIS_BREAKOUT_KEY = 'breakout_logs'
REDIS_STATUS_KEY   = 'solusdc_status'
REDIS_ACTIVITY_KEY = 'solusdc_activity_snapshots'
REDIS_ROLLING_KEY  = 'solusdc_rolling_metrics_logs'

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

CSS_PATH = os.path.join(os.path.dirname(__file__), 'dashboard.css')

# ── Data loading ──────────────────────────────────────────────────────────────

def load_json(key: str, limit: int = 60) -> list[dict]:
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
            ui.label('SOLUSDC · 1m').classes('header-ticker')
        with ui.row().classes('items-center gap-2'):
            ui.button('Buy',  on_click=lambda: ui.notify('Buy order placed',  color='positive')).classes('btn-buy')
            ui.button('Sell', on_click=lambda: ui.notify('Sell order placed', color='negative')).classes('btn-sell')

    # ── Main content ──────────────────────────────────────────────────────────
    with ui.column().classes('w-full q-pa-lg gap-6'):

        # ── Trade status cards ────────────────────────────────────────────────
        with ui.row().classes('w-full gap-3 flex-wrap'):
            with ui.element('div').classes('stat-card'):
                ui.label('Price').classes('stat-label')
                price_val = ui.label('—').classes('stat-value neutral')

            with ui.element('div').classes('stat-card'):
                ui.label('Floating P&L').classes('stat-label')
                pnl_val = ui.label('—').classes('stat-value neutral')

            with ui.element('div').classes('stat-card'):
                ui.label('Zone').classes('stat-label')
                zone_val = ui.label('—').classes('stat-value neutral')

            with ui.element('div').classes('stat-card'):
                ui.label('Entry Price').classes('stat-label')
                entry_val = ui.label('—').classes('stat-value neutral')

            with ui.element('div').classes('stat-card'):
                ui.label('Stop Price').classes('stat-label')
                stop_val = ui.label('—').classes('stat-value neutral')

            with ui.element('div').classes('stat-card'):
                ui.label('Target Price').classes('stat-label')
                target_val = ui.label('—').classes('stat-value neutral')



        # ── Tabbed tables ─────────────────────────────────────────────────────
        with ui.column().classes('w-full gap-2'):
            ui.label('Signal & Breakout Data').classes('section-title')

            with ui.tabs().props('align=left dense').classes('w-full') as tabs:
                tab_activity = ui.tab('Activity Snapshots').props('no-caps')
                tab_breakout = ui.tab('Breakout Log').props('no-caps')
                tab_rolling  = ui.tab('Rolling Metrics').props('no-caps')

            with ui.tab_panels(tabs, value=tab_activity).classes('w-full'):

                with ui.tab_panel(tab_activity):
                    activity_empty = ui.label('Waiting for activity snapshot data…').classes('empty-state')
                    activity_table = ui.table(columns=[], rows=[], row_key='timestamp').classes('data-table w-full')
                    activity_table.add_slot('body', '''
                        <q-tr :props="props" :class="props.row.is_qualified_activity ? 'qualified-row' : ''">
                            <q-td v-for="col in props.cols" :key="col.name" :props="props">
                                {{ col.value }}
                            </q-td>
                        </q-tr>
                    ''')

                with ui.tab_panel(tab_breakout):
                    breakout_empty = ui.label('Waiting for breakout data…').classes('empty-state')
                    breakout_table = ui.table(columns=[], rows=[], row_key='timestamp').classes('data-table w-full')

                with ui.tab_panel(tab_rolling):
                    rolling_empty = ui.label('Waiting for rolling metrics…').classes('empty-state')
                    rolling_table = ui.table(columns=[], rows=[], row_key='timestamp').classes('data-table w-full')

    # ── Periodic update ───────────────────────────────────────────────────────
    def update_ui():
        # ── Trade status (from execute layer) ─────────────────────────────────
        data = redis_client.hgetall(REDIS_STATUS_KEY)

        if data:
            price_val.text  = f"${data.get('current_price', '—')}"
            entry_val.text  = f"${data.get('entry_price', '—')}"
            stop_val.text   = f"${data.get('stop_price', '—')}"
            target_val.text = f"${data.get('target_price', '—')}"

            try:
                pnl_float = float(data.get('pnl', 0))
                sign = '+' if pnl_float >= 0 else ''
                pnl_val.classes(replace='stat-value profit' if pnl_float >= 0 else 'stat-value loss')
                pnl_val.text = f'{sign}{pnl_float:.2f}'
            except (ValueError, TypeError):
                pnl_val.text = '—'

            zone = data.get('zone', '—')
            zone_val.classes(replace='stat-value profit' if zone == 'Profit' else ('stat-value loss' if zone == 'Loss' else 'stat-value neutral'))
            zone_val.text = zone

        # ── Activity snapshot table ───────────────────────────────────────────
        activity_rows = load_json(REDIS_ACTIVITY_KEY)
        activity_empty.set_visibility(not activity_rows)
        activity_table.set_visibility(bool(activity_rows))
        if activity_rows:
            activity_table.columns = make_columns(activity_rows)
            activity_table.rows    = activity_rows
            activity_table.update()

        # ── Breakout log table ────────────────────────────────────────────────
        breakout_rows = load_json(REDIS_BREAKOUT_KEY)
        breakout_empty.set_visibility(not breakout_rows)
        breakout_table.set_visibility(bool(breakout_rows))
        if breakout_rows:
            breakout_table.columns = make_columns(breakout_rows)
            breakout_table.rows    = breakout_rows
            breakout_table.update()

        # ── Rolling metrics table ─────────────────────────────────────────────
        rolling_rows = load_json(REDIS_ROLLING_KEY)
        rolling_empty.set_visibility(not rolling_rows)
        rolling_table.set_visibility(bool(rolling_rows))
        if rolling_rows:
            rolling_table.columns = make_columns(rolling_rows)
            rolling_table.rows    = rolling_rows
            rolling_table.update()

    ui.timer(1.0, update_ui)

# ── Run ───────────────────────────────────────────────────────────────────────

ui.run(title='Ritrade', dark=True, favicon='📈')
