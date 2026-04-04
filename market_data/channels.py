GLOBAL_MINUTE_LOGS_KEY = 'minute_logs'
GLOBAL_ROLLING_METRICS_LOGS_KEY = 'rolling_metrics_logs'
GLOBAL_TRAP_LOGS_KEY = 'trap_logs'


def normalize_symbol(symbol: str) -> str:
    return symbol.lower()


def trade_events_channel(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_trade_events'


def kline_events_channel(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_kline_events'


def execution_price_channel(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_event_channel'


def latest_trade_event_key(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_latest_trade_event'


def latest_kline_event_key(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_latest_kline_event'


def activity_snapshots_key(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_activity_snapshots'


def minute_logs_key(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_minute_logs'


def rolling_metrics_key(symbol: str) -> str:
    return f'{normalize_symbol(symbol)}_rolling_metrics_logs'
