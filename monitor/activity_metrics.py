from __future__ import annotations

import math
from collections import deque

import numpy as np
from pydantic import BaseModel

from market_data.models import TradeEvent

ROLLING_WINDOW_MS = 10000
ACTIVITY_METRIC_VERSION = 1


class WindowMetrics(BaseModel):
    event_time_ms: int
    trade_count: int
    total_volume: float
    avg_price: float
    wap: float
    std_dev: float
    slope: float
    live_price: float | None = None


def calculate_wap(prices: list[float], quantities: list[float]) -> float:
    total_qty = sum(quantities)
    return sum(price * quantity for price, quantity in zip(prices, quantities)) / total_qty if total_qty else 0.0


def normalize_value(current_value: float, percentile_20: float, percentile_80: float) -> float:
    if current_value <= percentile_20:
        return 0.0
    if current_value >= percentile_80:
        return 1.0
    return (current_value - percentile_20) / (percentile_80 - percentile_20)


def trim_trades_to_window(
    trades: list[TradeEvent] | deque[TradeEvent],
    event_time_ms: int,
    *,
    window_ms: int = ROLLING_WINDOW_MS,
) -> list[TradeEvent]:
    cutoff_time = event_time_ms - window_ms
    return [trade for trade in trades if cutoff_time <= trade.event_time <= event_time_ms]


def compute_window_metrics(
    event_time_ms: int,
    trades: list[TradeEvent],
) -> WindowMetrics:
    prices = [trade.price for trade in trades]
    quantities = [trade.quantity for trade in trades]
    total_volume = sum(quantities)
    avg_price = np.mean(prices) if prices else 0.0
    std_dev = np.std(prices) if prices else 0.0
    slope = prices[-1] - prices[0] if len(prices) > 1 else 0.0
    wap = calculate_wap(prices, quantities)
    live_price = prices[-1] if prices else None

    return WindowMetrics(
        event_time_ms=event_time_ms,
        trade_count=len(trades),
        total_volume=float(total_volume),
        avg_price=float(avg_price),
        wap=float(wap),
        std_dev=float(std_dev),
        slope=float(slope),
        live_price=float(live_price) if live_price is not None else None,
    )


def floor_quantile(values: list[float] | list[int], percentile: float) -> int:
    return int(math.floor(float(np.quantile(values, percentile))))
