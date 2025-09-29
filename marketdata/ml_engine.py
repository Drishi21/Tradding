import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

# --- Machine Learning Predictor ---
def train_predictor(df: pd.DataFrame):
    df = df.dropna().copy()

    # Feature Engineering
    df["returns"] = df["Close"].pct_change()
    df["rsi_signal"] = np.where(df["RSI"] < 30, 1, np.where(df["RSI"] > 70, -1, 0))
    df["macd_signal"] = np.where(df["MACD"] > df["Signal"], 1, -1)

    # Target (next day up/down)
    df["target"] = np.where(df["Close"].shift(-1) > df["Close"], 1, 0)

    X = df[["returns", "RSI", "MACD", "Signal", "rsi_signal", "macd_signal"]].dropna()
    y = df["target"].loc[X.index]

    if len(X) < 50:  # not enough data
        return {"prediction": "Insufficient Data", "confidence": 0}

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    latest = X.iloc[[-1]]
    prediction = model.predict(latest)[0]
    prob = model.predict_proba(latest)[0][prediction]

    return {
        "prediction": "Bullish 📈" if prediction == 1 else "Bearish 📉",
        "confidence": round(prob * 100, 2),
    }


# --- Pattern Recognition (simplified example) ---
def detect_patterns(df: pd.DataFrame):
    patterns = []

    # Double Top: two recent highs within 2% range
    last_highs = df["High"].rolling(5).max().tail(10)
    if last_highs.max() - last_highs.min() < last_highs.max() * 0.02:
        patterns.append("Double Top 🏔️")

    # Double Bottom: two recent lows within 2% range
    last_lows = df["Low"].rolling(5).min().tail(10)
    if last_lows.max() - last_lows.min() < last_lows.min() * 0.02:
        patterns.append("Double Bottom 🏞️")

    return patterns or ["No major pattern detected"]


# --- Backtest Strategy ---
def backtest_strategy(df: pd.DataFrame):
    df = df.dropna().copy()
    balance = 100000
    position = 0

    for i in range(1, len(df)):
        if df["RSI"].iloc[i - 1] < 30 and balance > 0:  # Buy
            position = balance / df["Close"].iloc[i]
            balance = 0
        elif df["RSI"].iloc[i - 1] > 70 and position > 0:  # Sell
            balance = position * df["Close"].iloc[i]
            position = 0

    final = balance + (position * df["Close"].iloc[-1])
    return {
        "final_balance": round(final, 2),
        "pnl_percent": round((final - 100000) / 1000, 2),
    }
