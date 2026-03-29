### Notes

# ✅ Summary Flow

1. Take real price + volume from last 1-min + 20s
2. Compute avg price, std dev, slope, spread
3. Set trap distances based on volatility, slope tilt
4. Enforce minimum spread rule
5. Only deploy if volume + price are healthy

# ✅ Visual Summary

New 1-Min Candle Opens
↓
Start Collecting Trade Data
↓
At 20s:
Analyze avg price, volatility, slope, authenticity
↓
If Authentic:
↓
Calculate 4 Trap Prices
↓
Place 4 Limit Orders
↓
Monitor for Fill:
\- On Fill: set TP and SL
\- On No Fill by 59s: Cancel all
Else:
↓
Skip Traps for This Candle

## Naming Conventions

1 Minute ➔ made up of 12 x 5-second buckets

master\*\* = things across full minute
bucket\*\* = things for just 5s window
current_minute = which minute we are working in
current_bucket = which small bucket window we are in
already_triggered_20s = make sure trap happens only once per minute

## **Price Slope Interpretation**

| Price Slope ( momentum) | Meaning                      | Market Behaviour     |
| ----------------------- | ---------------------------- | -------------------- |
| ➕ Positive slope       | Price increased overall      | Bullish pressure     |
| ➖ Negative slope       | Price decreased overall      | Bearish Pressure     |
| ⚖️ Near-zero slope      | Price stayed flat / balanced | Neutral / indecisive |

| Condition                      | What it means          | Possible Action         |
| ------------------------------ | ---------------------- | ----------------------- |
| ✅  High std + high frequency  | Real Momentum          | Deploy volatility traps |
| ⚠️ High std + low frequency    | Manipulated / Fake     | Skip or Widen           |
| ✅  Low std + steady frequency | Calm, wait for impulse | Basic / Tight traps     |

Source | What I Calculate
1-min Candle | Trend direction (bullish/bearish/neutral)
20s Micro Price List | Volatility (how wild prices moved)
20s Price Slope | Momentum (mild or strong bias)
20s Spread (High–Low) | Micro risk estimate

/
