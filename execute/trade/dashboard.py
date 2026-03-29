import json
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
REDIS_STATUS_KEY = 'ethusdc_status'

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# -------------------------
# --- DATA LOADING ---
# -------------------------

def load_data():
    """Load breakout log data from Redis and return as DataFrame."""
    breakout_logs = json.loads(redis_client.get(REDIS_KEY) or '[]')
    return pd.DataFrame(breakout_logs)

# -------------------------
# --- PAGE ---
# -------------------------

@ui.page('/')
def main():
    df = load_data() if not load_data().empty else pd.DataFrame(columns=['placeholder'])
    columns = [{'name': col, 'label': col, 'field': col} for col in df.columns]
    rows = df.to_dict(orient='records')

    # -------------------------
    # --- UI COMPONENTS ---
    # -------------------------

    with ui.drawer(side='left') as drawer:
        drawer.props('width=250 behavior=push')
        ui.label('📚 Menu').style('font-size: 20px; font-weight: bold; margin-bottom: 10px;')
        ui.link('Volatility Breakout', '/')
        ui.link('Logs', '/')

    price_label = ui.label('Current price: N/A')
    ui.label('📊 Trades').style('font-size: 32px; font-weight: bold; margin-bottom: 10px;')

    with ui.column().classes('w-full'):
        with ui.row().classes('w-full'):
            ui.table(columns=columns, rows=rows, row_key=df.columns[0] if not df.empty else None).classes('ticker-table')

        with ui.tabs().props('align:left') as tabs:
            one = ui.tab('BTCUSDC')
            ui.tab('Other')

        with ui.tab_panels(tabs, value=one).classes('w-full'):
            with ui.tab_panel(one):
                with ui.column().classes('w-full'):
                    with ui.row().classes('gap-1 justify-end'):
                        ui.button('Buy', on_click=lambda: ui.notify('Buy clicked!'))
                        ui.button('Sell', on_click=lambda: ui.notify('Sell clicked!'), color='red')
                    with ui.row().classes('w-full'):
                        ticker_table = ui.table(columns=columns, rows=rows, row_key=df.columns[0] if not df.empty else None).classes('ticker-table')

    # -------------------------
    # --- CUSTOM CSS ---
    # -------------------------

    ui.add_head_html('''
    <style>
    .ticker-table { width: 100%; border: 1px solid #ccc; border-radius: 8px; overflow: hidden; }
    .q-table thead { background-color: #f0f0f0; font-weight: bold; font-size: 16px; color: #333; }
    </style>
    ''')

    # -------------------------
    # --- PERIODIC UPDATE ---
    # -------------------------

    def update_ui():
        """Poll Redis every second and refresh UI components."""
        data = redis_client.hgetall(REDIS_STATUS_KEY)
        if data and 'current_price' in data:
            price_label.text = f"Current price: {data['current_price']}"
        else:
            price_label.text = "Current price: N/A"

        new_df = load_data()
        if not new_df.empty:
            ticker_table.rows = new_df.to_dict(orient='records')
            ticker_table.update()

    ui.timer(1.0, update_ui)

# -------------------------
# --- RUN APP ---
# -------------------------

ui.run(title='Volatility Breakout')
