
from datetime import datetime


def format_timestamp(ms):
    return datetime.fromtimestamp(ms / 1000).strftime('%H:%M:%S')

def volatility_breakout(buffer, breakout_logs):
    """
    Process breakout logic and log minute data.

    Args:
        buffer (list): List of candlestick data.
        breakout_logs (list): List to store breakout log data.

    Returns:
        None
    """
    
    # Check if buffer is sufficiently filled
    if len(buffer) < 2:
        return 

    # Calculate range
    highs = [c['high'] for c in buffer[:-1]]
    lows = [c['low'] for c in buffer[:-1]]
    recent_high = max(highs)
    recent_low = min(lows)

    # Check for breakout
    recent_open = buffer[-1]['open']
    recent_close = buffer[-1]['close']
    breakoutUp = recent_close > recent_high         #trigger long trade
    breakoutDown = recent_close < recent_low        #trigger short trade

    # Log minute data
    breakout_log_data = {
        "timestamp": format_timestamp(buffer[-1]['close_time']),
        "high": recent_high,
        "low": recent_low,
        "open": recent_open,
        "close": recent_close,
        "breakoutUp": breakoutUp,
        "breakoutDown": breakoutDown
    }

    # Insert into breakout logs (most recent at the top)
    breakout_logs.insert(0, breakout_log_data)