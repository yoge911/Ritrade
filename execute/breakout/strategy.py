from core_utils.format import format_timestamp
from execute.models.candle import Candle
from execute.models.breakout_log import BreakoutLog


def volatility_breakout(buffer: list[dict], breakout_logs: list) -> None:
    """
    Process breakout logic on the candle buffer and append to breakout_logs.

    Args:
        buffer: List of raw candle dicts from Kline.
        breakout_logs: List to prepend the new BreakoutLog entry to.
    """
    if len(buffer) < 2:
        return

    candles = [Candle(**c) for c in buffer]

    recent_high = max(c.high for c in candles[:-1])
    recent_low  = min(c.low  for c in candles[:-1])

    last = candles[-1]

    log = BreakoutLog(
        timestamp=format_timestamp(last.close_time),
        high=recent_high,
        low=recent_low,
        open=last.open,
        close=last.close,
        breakoutUp=last.close > recent_high,
        breakoutDown=last.close < recent_low,
    )

    breakout_logs.insert(0, log.model_dump())