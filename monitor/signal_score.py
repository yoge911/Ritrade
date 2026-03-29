import pandas as pd
import numpy as np

def compute_micro_signal_score(df, window=5):
    """
    Compute a micro signal strength score based on:
    - Buy/Sell volume pressure
    - Momentum over a rolling window
    - Spread efficiency
    Input:
        df: DataFrame with columns ['price', 'buy_volume', 'sell_volume', 'spread']
        window: Rolling window size for momentum (default=5)
    Output:
        DataFrame with additional columns:
        - volume_ratio
        - momentum
        - spread_score
        - micro_score (final score out of 100)
    """
    df = df.copy()

    # Calculate supporting metrics
    df["volume_ratio"] = df["buy_volume"] / df["sell_volume"]
    df["price_change"] = df["price"].diff().fillna(0)
    df["momentum"] = df["price_change"].rolling(window=window).sum().fillna(0)
    df["spread_score"] = 1 / df["spread"].replace(0, np.nan)  # Avoid div by zero

    # Normalize and score components
    volume_score = (df["volume_ratio"] - 1).clip(lower=0)
    momentum_score = df["momentum"].clip(lower=0)
    spread_score = df["spread_score"]

    # Safe normalization
    volume_max = volume_score.max() if volume_score.max() != 0 else 1
    momentum_max = momentum_score.max() if momentum_score.max() != 0 else 1
    spread_max = spread_score.max() if spread_score.max() != 0 else 1

    # Weighted score composition
    df["micro_score"] = (
        (volume_score / volume_max) * 0.5 +
        (momentum_score / momentum_max) * 0.3 +
        (spread_score / spread_max) * 0.2
    ) * 100

    return df
