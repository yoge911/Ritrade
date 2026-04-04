from datetime import datetime

def format_timestamp(ms):
    return datetime.fromtimestamp(ms / 1000).strftime('%H:%M:%S.%f')[:-3]
