# marketdata/utils.py

import json
import gzip
import io
import datetime
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from django.conf import settings
from .models import MarketRecord, MarketNews, FiiDiiRecord

# ----------------------------
# Helpers
# ----------------------------
def safe_json(response):
    """Safe JSON decode with debug preview"""
    try:
        return response.json()
    except Exception as e:
        print("⚠️ JSON decode failed:", e)
        print("Response text (first 300 chars):", response.text[:300])
        return {}


# ----------------------------
# Nifty history fetchers
# ----------------------------
def fetch_from_nse(days=365):
    """
    Fallback: fetch NIFTY 50 history directly from NSE API
    """
    session = requests.Session()
    session.headers.update(NSE_HEADERS)

    # Warmup to set cookies
    session.get("https://www.nseindia.com", timeout=10)

    url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
    resp = session.get(url, timeout=15)

    # Handle gzip manually if needed
    try:
        if resp.headers.get("Content-Encoding") == "gzip":
            buf = io.BytesIO(resp.content)
            f = gzip.GzipFile(fileobj=buf)
            data = json.loads(f.read().decode("utf-8"))
        else:
            data = resp.json()
    except Exception as e:
        print(f"⚠️ NSE decode failed: {e}")
        print(resp.text[:300])
        return []

    # Parse daily records
    records = []
    prev_close = None
    for item in reversed(data["data"][-days:]):  # take last X days
        close = float(item["CLOSE"])
        points = 0 if prev_close is None else round(close - prev_close, 2)
        records.append({
            "date": pd.to_datetime(item["TIMESTAMP"]).date(),
            "open": float(item["OPEN"]),
            "high": float(item["HIGH"]),
            "low": float(item["LOW"]),
            "close": close,
            "points": points,
        })
        prev_close = close

    return records


import requests
import pandas as pd
from datetime import datetime, timedelta

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}

from nselib import capital_market as cm
from datetime import datetime, date, timedelta

# Yahoo Finance: Nifty OHLC
def fetch_nifty_history(days=365):
    """
    Fetch NIFTY 50 daily OHLC using nselib.capital_market.index_data
    """
    to_date = date.today()
    from_date = to_date - timedelta(days=days)

    # Correct date format for nselib input: '%d-%m-%Y' (e.g., '21-09-2025')
    formatted_from_date = from_date.strftime("%d-%m-%Y")
    formatted_to_date = to_date.strftime("%d-%m-%Y")

    try:
        data = cm.index_data(
            index="NIFTY 50",
            from_date=formatted_from_date,
            to_date=formatted_to_date
        )
        
        # Check if data is empty before processing
        if data.empty:
            print("⚠️ nselib returned an empty DataFrame.")
            return []
        
        records = []
        prev_close = None
        for index, row in data.iterrows():
            close = float(row.get("CLOSE_INDEX_VAL"))
            points = 0 if prev_close is None else round(close - prev_close, 2)
            records.append({
                # Correct format for parsing the 'TIMESTAMP' column from nselib output: '%d-%m-%Y'
                "date": datetime.strptime(row["TIMESTAMP"], "%d-%m-%Y").date(), 
                "open": float(row.get("OPEN_INDEX_VAL")),
                "high": float(row.get("HIGH_INDEX_VAL")),
                "low": float(row.get("LOW_INDEX_VAL")),
                "close": close,
                "points": points,
            })
            prev_close = close
            
        return records
    except Exception as e:
        print(f"❌ Error fetching NIFTY history with nselib: {e}")
        return []

# ----------------------------
# Save daily + hourly into DB
# ----------------------------
def save_yearly_with_hourly(days=30):
    nifty = yf.Ticker("^NSEI")

    # 1️⃣ Daily candles
    daily_hist = nifty.history(period=f"{days}d").reset_index()
    prev_close = None
    for _, row in daily_hist.iterrows():
        close = float(row["Close"])
        points = 0 if prev_close is None else round(close - prev_close, 2)
        MarketRecord.objects.update_or_create(
            date=row["Date"].date(),
            hour=None,  # daily record
            defaults={
                "nifty_open": float(row["Open"]),
                "nifty_high": float(row["High"]),
                "nifty_low": float(row["Low"]),
                "nifty_close": close,
                "points": points,
            }
        )
        prev_close = close

    # 2️⃣ Hourly candles (only last 60 days supported reliably)
    hourly_hist = nifty.history(period="60d", interval="1h").reset_index()
    for _, row in hourly_hist.iterrows():
        MarketRecord.objects.update_or_create(
            date=row["Datetime"].date(),
            hour=row["Datetime"].time().replace(minute=0, second=0, microsecond=0),
            defaults={
                "nifty_open": float(row["Open"]),
                "nifty_high": float(row["High"]),
                "nifty_low": float(row["Low"]),
                "nifty_close": float(row["Close"]),
                "points": 0,
            }
        )


# ----------------------------
# Market Indicators
# ----------------------------
def fetch_pcr():
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=NSE_HEADERS)
    res = session.get(url, headers=NSE_HEADERS)
    data = safe_json(res)

    try:
        ce_oi = sum([d["CE"]["openInterest"] for d in data["records"]["data"] if "CE" in d])
        pe_oi = sum([d["PE"]["openInterest"] for d in data["records"]["data"] if "PE" in d])
        return round(pe_oi / ce_oi, 2) if ce_oi > 0 else 0
    except Exception:
        return 0



# ----------------------------
# News
# ----------------------------
def fetch_news():
    api_key = getattr(settings, "NEWS_API_KEY", None)
    if not api_key:
        return "No API key configured"

    url = f"https://newsapi.org/v2/everything?q=Nifty%20OR%20Stock%20Market&apiKey={api_key}"
    res = requests.get(url).json()
    headlines = [a["title"] for a in res.get("articles", [])[:5]]
    return "; ".join(headlines)
