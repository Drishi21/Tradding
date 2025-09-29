# marketdata/views.py (relevant parts)
import logging
import json
from datetime import datetime, date, timedelta, time
import requests
from bs4 import BeautifulSoup
import pandas as pd
import yfinance as yf

from django.shortcuts import render, redirect
from django.core.paginator import Paginator

from .models import MarketRecord, FiiDiiRecord

logger = logging.getLogger(__name__)

# ---------- Helpers: HTTP session with retries (optional) ----------
def requests_session_with_retries():
    s = requests.Session()
    # optional: add retries
    from requests.adapters import HTTPAdapter, Retry
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=(500,502,503,504))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "Mozilla/5.0 (market-tracker)"})
    return s

# ---------- Fetch PCR (live only) ----------
def fetch_pcr_data(symbol="NIFTY"):
    """Fetch current PCR from NSE option chain. Live only — NSE does not provide historical snapshots."""
    try:
        session = requests_session_with_retries()
        # seed
        session.get("https://www.nseindia.com", timeout=5)
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        res = session.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        ce_oi = sum([item["CE"]["openInterest"] for item in data["records"]["data"] if "CE" in item])
        pe_oi = sum([item["PE"]["openInterest"] for item in data["records"]["data"] if "PE" in item])
        return round(pe_oi / ce_oi, 2) if ce_oi else 0
    except Exception as e:
        logger.exception("PCR fetch failed")
        return 0

# ---------- Fetch FII/DII (Groww scraping) ----------
def fetch_fii_dii():
    """
    Scrape Groww (or similar) and return list of dicts:
    [{'date': '2025-09-25', 'fii_buy':..., 'fii_sell':..., 'fii_net':..., 'dii_buy':..., ...}, ...]
    If the website structure changes you'll have to update this parser.
    """
    try:
        s = requests_session_with_retries()
        url = "https://groww.in/fii-dii-data"
        r = s.get(url, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script:
            logger.error("Could not find __NEXT_DATA__ on groww page")
            return []
        data = json.loads(script.string)
        # NOTE: field path depends on the site; adjust if needed
        raw = data.get("props", {}).get("pageProps", {}).get("initialData", [])
        parsed = []
        for row in raw:
            parsed.append({
                "date": row.get("date"),
                "fii_buy": float(row.get("fii", {}).get("grossBuy", 0) or 0),
                "fii_sell": float(row.get("fii", {}).get("grossSell", 0) or 0),
                "fii_net": float(row.get("fii", {}).get("netBuySell", 0) or 0),
                "dii_buy": float(row.get("dii", {}).get("grossBuy", 0) or 0),
                "dii_sell": float(row.get("dii", {}).get("grossSell", 0) or 0),
                "dii_net": float(row.get("dii", {}).get("netBuySell", 0) or 0),
            })
        return parsed
    except Exception as e:
        logger.exception("fetch_fii_dii failed")
        return []

def fetch_fii_dii_map():
    lst = fetch_fii_dii()
    out = {}
    for r in lst:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
            out[d] = r
        except Exception:
            logger.warning("Skipping invalid date in FII/DII row: %s", r)
    return out

# ---------- Fetch NIFTY history (daily + 1h + 30m) ----------
def fetch_nifty_history(days=30, include_hourly=True, include_30m=True):
    """
    Returns a list of dicts:
    {
      "date": datetime.date(...),
      "hour": None or datetime.time(...),
      "interval": "1d"|"1h"|"30m",
      "open": float, "high": float, "low": float, "close": float, "points": float
    }
    The list contains daily rows (hour=None) + intraday rows.
    """
    try:
        ticker = yf.Ticker("^NSEI")
        records = []
        prev_daily_close = None

        # --- Daily ---
        df_daily = ticker.history(period=f"{days}d", interval="1d")
        if not df_daily.empty:
            for ts, row in df_daily.iterrows():
                py_dt = pd.to_datetime(ts).to_pydatetime()
                close = float(row["Close"])
                points = 0 if prev_daily_close is None else round(close - prev_daily_close, 2)
                records.append({
                    "date": py_dt.date(),
                    "hour": None,
                    "interval": "1d",
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": close,
                    "points": points,
                })
                prev_daily_close = close

        # --- Hourly (1h) ---
        if include_hourly:
            df_h = ticker.history(period=f"{max(7, days)}d", interval="1h")
            if not df_h.empty:
                for ts, row in df_h.iterrows():
                    py_dt = pd.to_datetime(ts).to_pydatetime()
                    # normalize time (drop seconds/microseconds)
                    t = py_dt.time().replace(second=0, microsecond=0)
                    # keep only the top-of-hour (minute==0) rows as hourly series
                    if t.minute == 0:
                        records.append({
                            "date": py_dt.date(),
                            "hour": t,
                            "interval": "1h",
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "points": 0.0,
                        })

        # --- 30 minute ---
        if include_30m:
            df_30 = ticker.history(period=f"{max(7, days)}d", interval="30m")
            if not df_30.empty:
                for ts, row in df_30.iterrows():
                    py_dt = pd.to_datetime(ts).to_pydatetime()
                    t = py_dt.time().replace(second=0, microsecond=0)
                    # we store only the 30-minute stamps (minute == 30) to avoid duplicating hourly rows
                    if t.minute == 30:
                        records.append({
                            "date": py_dt.date(),
                            "hour": t,
                            "interval": "30m",
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "points": 0.0,
                        })

        # Sort so daily first (by date asc or desc doesn't matter); we'll save them
        # We'll return sorted by date asc then hour (None first)
        records.sort(key=lambda r: (r["date"], (r["hour"] or time(0,0))))
        return records

    except Exception as e:
        logger.exception("Error fetching nifty history")
        return []

# -------------------- record_list view --------------------
def record_list(request):
    filter_option = request.GET.get("filter", "all")
    selected_date = request.GET.get("snippet_date")

    if request.method == "POST" and "update_data" in request.POST:
        # Fetch market data
        nifty_records = fetch_nifty_history(days=30, include_hourly=True, include_30m=True)

        # Fetch FII/DII map
        fii_map = fetch_fii_dii_map()
        today = date.today()

        # Save items to DB. Process daily rows first (hour == None), then intraday
        # To ensure daily FII/DII applied to intraday we can process by sorting date + hour(None first)
        for r in nifty_records:
            date_val = r["date"]
            hour_val = r["hour"]  # None for daily, time for intraday
            fii_info = fii_map.get(date_val, {})

            if hour_val is None:
                # daily
                existing = MarketRecord.objects.filter(date=date_val, hour__isnull=True).first()
                if date_val == today:
                    pcr_val = fetch_pcr_data()
                else:
                    pcr_val = existing.pcr if existing else 0

                defaults = {
                    "nifty_open": r["open"],
                    "nifty_high": r["high"],
                    "nifty_low": r["low"],
                    "nifty_close": r["close"],
                    "points": r["points"],
                    # FII/DII fields from the map (if present)
                    "fii_buy": fii_info.get("fii_buy", 0),
                    "fii_sell": fii_info.get("fii_sell", 0),
                    "fii_net": fii_info.get("fii_net", 0),
                    "dii_buy": fii_info.get("dii_buy", 0),
                    "dii_sell": fii_info.get("dii_sell", 0),
                    "dii_net": fii_info.get("dii_net", 0),
                    "pcr": pcr_val,
                    "global_markets": "Auto fetch pending",
                    "decision": "Bullish" if float(r["points"]) > 0 else "Bearish",
                    "important_news": existing.important_news if existing else "",
                }
                MarketRecord.objects.update_or_create(date=date_val, hour=None, defaults=defaults)
            else:
                # intraday (hourly or 30m)
                # copy FII/DII daily numbers into intraday rows (so UI can show them)
                defaults = {
                    "nifty_open": r["open"],
                    "nifty_high": r["high"],
                    "nifty_low": r["low"],
                    "nifty_close": r["close"],
                    "points": r["points"],
                    "fii_buy": fii_info.get("fii_buy", 0),
                    "fii_sell": fii_info.get("fii_sell", 0),
                    "fii_net": fii_info.get("fii_net", 0),
                    "dii_buy": fii_info.get("dii_buy", 0),
                    "dii_sell": fii_info.get("dii_sell", 0),
                    "dii_net": fii_info.get("dii_net", 0),
                    "pcr": 0,
                    "decision": "Bullish" if float(r["points"]) > 0 else "Bearish",
                }
                MarketRecord.objects.update_or_create(date=date_val, hour=hour_val, defaults=defaults)

        return redirect("record_list")

    # ========== display: daily query and filters ==========
    daily_qs = MarketRecord.objects.filter(hour__isnull=True).order_by("-date")
    today = date.today()

    if filter_option == "today":
        daily_qs = daily_qs.filter(date=today)
    elif filter_option == "yesterday":
        daily_qs = daily_qs.filter(date=today - timedelta(days=1))
    elif filter_option == "week":
        start_of_week = today - timedelta(days=today.weekday())
        daily_qs = daily_qs.filter(date__gte=start_of_week, date__lte=today)
    elif filter_option == "month":
        daily_qs = daily_qs.filter(date__year=today.year, date__month=today.month)
    elif filter_option == "3months":
        daily_qs = daily_qs.filter(date__gte=today - timedelta(days=90), date__lte=today)
    # optional: weekday filtering
    elif filter_option in ["monday","tuesday","wednesday","thursday","friday"]:
        weekdays = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4}
        daily_qs = daily_qs.filter(date__week_day=weekdays[filter_option]+2)

    all_records = list(daily_qs)

    # compute points for daily rows (based on previous trading day close)
    prev_close = None
    for rec in reversed(all_records):
        rec.points = 0 if prev_close is None else round(float(rec.nifty_close) - float(prev_close), 2)
        prev_close = rec.nifty_close

    # paginate
    paginator = Paginator(all_records, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    # For each daily record prepare two intraday lists:
    # - hourly (minute == 0)
    # - min30 (minute == 30)
    for rec in page_obj:
        intraday_qs = MarketRecord.objects.filter(date=rec.date, hour__isnull=False).order_by("hour")
        hourly = []
        min30 = []
        # calculate intraday points relative to previous intraday close (starting fresh each day)
        prev_intraday_close = None
        for it in intraday_qs:
            it.points = 0 if prev_intraday_close is None else round(float(it.nifty_close) - float(prev_intraday_close), 2)
            prev_intraday_close = it.nifty_close
            if it.hour and it.hour.minute == 0:
                hourly.append(it)
            elif it.hour and it.hour.minute == 30:
                min30.append(it)
        rec.hourly_set_calculated = hourly
        rec.min30_set_calculated = min30

    # working-day snippets
    working_days = [r for r in all_records if r.date.weekday() < 5]
    def trade_snippet(days):
        records = working_days[:days]
        if not records:
            return {"trend":"-","trade":"-"}
        avg = sum(float(r.points) for r in records)/len(records)
        return {"trend":"Bullish" if avg>=0 else "Bearish","trade":"Call" if avg>=0 else "Put"}

    snippets = {
        "Based on Last 25 Working Days": trade_snippet(25),
        "Based on Last 15 Working Days": trade_snippet(15),
        "Based on Last 1 Week": trade_snippet(7),
        "Based on Last 3 Working Days": trade_snippet(3),
        "Based on Last 2 Working Days": trade_snippet(2),
        "Based on Last 1 Working Day": trade_snippet(1),
    }

    # summary stats
    total_days = len(working_days)
    bullish_days = len([r for r in working_days if r.decision == "Bullish"])
    bearish_days = len([r for r in working_days if r.decision == "Bearish"])
    neutral_days = total_days - (bullish_days + bearish_days)
    bullish_percent = round((bullish_days / total_days) * 100, 1) if total_days else 0
    bearish_percent = round((bearish_days / total_days) * 100, 1) if total_days else 0
    neutral_percent = round((neutral_days / total_days) * 100, 1) if total_days else 0

    last = all_records[0] if all_records else None

    context = {
        "records": page_obj,
        "filter_option": filter_option,
        "snippets": snippets,
        "snippet_date": selected_date or today.isoformat(),
        "bullish_percent": bullish_percent,
        "bearish_percent": bearish_percent,
        "neutral_percent": neutral_percent,
        "last": last,
    }
    return render(request, "marketdata/record_list.html", context)
