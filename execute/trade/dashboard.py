import json
import os
import pandas as pd
import redis
from nicegui import ui

# -------------------------
# --- CONFIGURATION ---
# -------------------------

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_KEY = 'breakout_logs'
REDIS_STATUS_KEY = 'solusdc_status'

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

CSS_PATH = os.path.join(os.path.dirname(__file__), 'dashboard.css')

# -------------------------
# --- DATA LOADING ---
# -------------------------

def load_data():
    breakout_logs = json.loads(redis_client.get(REDIS_KEY) or '[]')
    return pd.DataFrame(breakout_logs)

# -------------------------
# --- PAGE ---
# -------------------------

@ui.page('/')
def main():
    with open(CSS_PATH) as f:
        ui.add_head_html(f'<style>{f.read()}</style>')

    df = load_data()
    columns = [{'name': col, 'label': col.upper(), 'field': col, 'align': 'left'} for col in df.columns] if not df.empty else []
    rows = df.to_dict(orient='records')

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

        # ── Status cards ──────────────────────────────────────────────────────
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

        # ── Breakout log table ────────────────────────────────────────────────
        with ui.column().classes('w-full gap-2'):
            ui.label('Breakout Log').classes('section-title')
            with ui.tabs().props('align=left dense').classes('w-full') as tabs:
                one = ui.tab('SOLUSDC').props('no-caps')
                ui.tab('Other').props('no-caps')

            with ui.tab_panels(tabs, value=one).classes('w-full'):
                with ui.tab_panel(one):
                    ticker_table = ui.table(
                        columns=columns,
                        rows=rows,
                        row_key=df.columns[0] if not df.empty else 'timestamp'
                    ).classes('breakout-table w-full')

    # ── Periodic update ───────────────────────────────────────────────────────
    def update_ui():
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

        new_df = load_data()
        if not new_df.empty:
            ticker_table.rows = new_df.to_dict(orient='records')
            ticker_table.update()

    ui.timer(1.0, update_ui)

# -------------------------
# --- RUN APP ---
# -------------------------

ui.run(title='Ritrade', dark=True, favicon='📈')