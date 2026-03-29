# streamlit_app.py
import streamlit as st
import pandas as pd
from datetime import datetime
import redis
import json
from streamlit_autorefresh import st_autorefresh


# Auto-refresh
st.set_page_config(page_title="🚀 Ritrade Dashboard", layout="wide")
st_autorefresh(interval=1000, key="data_refresh")  # Refresh every second

# Initialize Redis connection
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Load live data from Redis
trap_logs = json.loads(r.get("trap_logs") or "[]")
minute_logs = json.loads(r.get("minute_logs") or "[]")
rolling_metrics_logs = json.loads(r.get("rolling_metrics_logs") or "[]")

# Title
st.title("🚀 Dashboard")
st.markdown("---")


# Tabs
tab1, tab2, tab3 = st.tabs(["📊 Micro Buckets (10s)", "🛠️ 20s Trap Snapshots", "⏱️ 1-Minute Summary"])

# Convert to DataFrames
rolling_metrics_logs_df = pd.DataFrame(rolling_metrics_logs)
trap_df = pd.DataFrame(trap_logs)
minute_df = pd.DataFrame(minute_logs)




# Display tables inside tabs
with tab1:
    st.subheader("📊 (10s Rolling Window)")
    if not rolling_metrics_logs_df.empty:
        st.dataframe(rolling_metrics_logs_df.tail(60).iloc[::-1])
    else:
        st.info("Waiting for Rolling Metrics data...")

with tab2:
    st.subheader("🛠️ 20s Trap Snapshots")
    if not trap_df.empty:
        st.dataframe(trap_df.tail(60).iloc[::-1])
    else:
        st.info("Waiting for trap snapshots...")

with tab3:
    st.subheader("⏱️ 1-Minute Candle Summary")
    if not minute_df.empty:
        st.dataframe(minute_df.tail(60).iloc[::-1])
    else:
        st.info("Waiting for 1-min candle summaries...")

# Footer
st.caption(f"⏰ Last refreshed: {datetime.now().strftime('%H:%M:%S')}")
