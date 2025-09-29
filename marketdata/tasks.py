from .models import MarketRecord
from datetime import date

# def save_yearly_records():
#     nifty_records = fetch_nifty_history(365)
#         # Try fetching APIs
#     try:
#         fii_dii_data = fetch_fii_dii()
#     except Exception:
#         fii_dii_data = {}

#     try:
#         pcr_value = fetch_pcr()
#     except Exception:
#         pcr_value = None

#     try:
#         news = fetch_news()
#     except Exception:
#         news = ""
    
#     for r in nifty_records:
#         # fallback: check last saved record
#         existing = MarketRecord.objects.filter(date=r["date"]).first()

#         fii = fii_dii_data.get(r["date"], {}).get("fii", None)
#         dii = fii_dii_data.get(r["date"], {}).get("dii", None)

#         if fii is None and existing:
#             fii = existing.fii
#         if dii is None and existing:
#             dii = existing.dii
#         if pcr_value is None and existing:
#             pcr = existing.pcr
#         else:
#             pcr = pcr_value

#         MarketRecord.objects.update_or_create(
#             date=r["date"],
#             defaults={
#                 "nifty_open": r["open"],
#                 "nifty_high": r["high"],
#                 "nifty_low": r["low"],
#                 "nifty_close": r["close"],
#                 "points": r["points"],
#                 "fii": fii if fii is not None else 0,
#                 "dii": dii if dii is not None else 0,
#                 "pcr": pcr if pcr is not None else 0,
#                 "global_markets": "Auto fetch pending",
#                 "decision": "Bullish" if r["points"] > 0 else "Bearish",
#                 "important_news": news if news else (existing.important_news if existing else ""),
#             }
#         )
import yfinance as yf

from .utils import fetch_nifty_history, fetch_fii_dii, fetch_pcr, fetch_news
from .models import MarketRecord

def save_yearly_records():
    nifty_records = fetch_nifty_history(365)

    # fetch supplementary data
    try:
        fii_dii_data = fetch_fii_dii()
    except Exception as e:
        print(e)
        fii_dii_data = {}

    try:
        pcr_value = fetch_pcr()
    except Exception as e:
        print(e)
        pcr_value = None

    try:
        news = fetch_news()
    except Exception:
        news = ""

    # 🔹 Save daily data
    prev_close = None
    for r in nifty_records:
        existing = MarketRecord.objects.filter(date=r["date"], hour=None).first()

        fii = fii_dii_data.get(r["date"], {}).get("fii", existing.fii if existing else 0)
        dii = fii_dii_data.get(r["date"], {}).get("dii", existing.dii if existing else 0)
        pcr = pcr_value if pcr_value is not None else (existing.pcr if existing else 0)

        MarketRecord.objects.update_or_create(
            date=r["date"], hour=None,
            defaults={
                "nifty_open": r["open"],
                "nifty_high": r["high"],
                "nifty_low": r["low"],
                "nifty_close": r["close"],
                "points": r["points"],
                "fii": fii,
                "dii": dii,
                "pcr": pcr,
                "global_markets": "Auto fetch pending",
                "decision": "Bullish" if r["points"] > 0 else "Bearish",
                "important_news": news if news else (existing.important_news if existing else ""),
            }
        )
        prev_close = r["close"]

    # 🔹 Save hourly data (only last 60 days supported)
    nifty = yf.Ticker("^NSEI")
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
                "fii": 0,
                "dii": 0,
                "pcr": 0,
                "global_markets": "",
                "decision": "Bullish" if row["Close"] >= row["Open"] else "Bearish",
                "important_news": "",
            }
        )
