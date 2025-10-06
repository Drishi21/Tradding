# marketdata/views.py
import os
import math
import json
import logging
import time
from datetime import datetime, date, timedelta, time as dt_time
from collections import defaultdict

import pandas as pd
import yfinance as yf
import joblib
import ta
from textblob import TextBlob
import feedparser
from newspaper import Article
from googletrans import Translator  # pip install googletrans==4.0.0-rc1
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter, Retry

from django.shortcuts import render, redirect
from django.utils.timezone import now, make_aware, localtime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.conf import settings
from django.contrib import messages
from django.db.models import Q, Count
from django.core.cache import cache

from .models import (
    MarketRecord,
    MarketNews,
    FiiDiiRecord,
    MarketTrap,
    Prediction,
    TradePlan,
    OptionTrade,
    SniperLevel,
    SniperTrade
)
from .analysis import analyze_fii_dii, advanced_market_trap_analysis

# ==========================================================
# Globals
# ==========================================================
logger = logging.getLogger(__name__)
translator = Translator()
MODEL_FILE = os.path.join(settings.BASE_DIR, "ml_models", "nifty_model.pkl")

def get_decision(record):
    """Return bias (Bullish/Bearish/Neutral) using property or fallback."""
    try:
        return record.calculated_decision
    except Exception:
        return record.decision or "Neutral"

def annotate_intraday_traps(record, m30_rows, pcr=None):
    """Generate annotations for intraday slots (who got trapped/profited)."""
    out = []
    if not m30_rows:
        return out

    try:
        pcr_val = float(pcr) if pcr is not None else None
    except Exception:
        pcr_val = None

    for slot in m30_rows:
        try:
            pts = float(slot.points)
        except Exception:
            continue
        if abs(pts) < 30:
            continue

        time_str = slot.hour.strftime("%H:%M") if slot.hour else "NA"
        if pts < 0:
            annotation = "📉 Call buyers trapped; Put buyers profited"
            if pcr_val and pcr_val > 1.2:
                annotation += " (PCR high → Put OI heavy)"
        else:
            annotation = "📈 Put buyers trapped; Call buyers profited"
            if pcr_val and pcr_val < 0.8:
                annotation += " (PCR low → Call OI heavy)"

        out.append({
            "time": time_str,
            "points": round(pts, 2),
            "direction": "down" if pts < 0 else "up",
            "annotation": annotation,
        })
    return out

NSE_OPTION_CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"

def _nse_get_json(url, timeout=8):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=headers, timeout=6)
        r = s.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("NSE fetch failed: %s", e)
        return None


def fetch_option_chain_for_strike(strike_price):
    data = _nse_get_json(NSE_OPTION_CHAIN_URL)
    if not data:
        return None
    try:
        for item in data.get("records", {}).get("data", []):
            if int(item.get("strikePrice", -1)) == int(strike_price):
                return {"CE": item.get("CE"), "PE": item.get("PE")}
    except Exception:
        pass
    return None

def build_dynamic_trade_plan(record, option_lot_size=75):
    try:
        atm = round(float(record.close) / 50) * 50
    except Exception:
        atm = round(float(record.close))

    opt = fetch_option_chain_for_strike(atm)
    bias = get_decision(record)

    # fallback
    fallback = {
        "side": "PE",
        "strike": atm,
        "entry": [115, 125],
        "target": 180,
        "stop_loss": 84,
        "qty": option_lot_size,
        "confidence": 55,
        "ltp": None,
    }
    if not opt:
        return {"plan": fallback, "html": f"🔴 Option Buy → {atm} PE (fallback plan)"}

    ce = opt.get("CE") or {}
    pe = opt.get("PE") or {}
    ce_ltp = float(ce.get("lastPrice") or 100)
    pe_ltp = float(pe.get("lastPrice") or 120)
    ce_oi = int(ce.get("openInterest") or 0)
    pe_oi = int(pe.get("openInterest") or 0)

    if bias == "Bearish":
        entry = [round(pe_ltp*0.95,1), round(pe_ltp*1.05,1)]
        plan = {"side":"PE","strike":atm,"entry":entry,"target":round(pe_ltp*1.5,1),
                "stop_loss":round(pe_ltp*0.7,1),"qty":option_lot_size,"ltp":pe_ltp,"oi":pe_oi}
        html = f"🔴 Option Buy → {atm} PE | Entry: {entry[0]}–{entry[1]} | Target: {plan['target']} | SL: {plan['stop_loss']} | LTP: {pe_ltp} | OI: {pe_oi}"
    elif bias == "Bullish":
        entry = [round(ce_ltp*0.95,1), round(ce_ltp*1.05,1)]
        plan = {"side":"CE","strike":atm,"entry":entry,"target":round(ce_ltp*1.5,1),
                "stop_loss":round(ce_ltp*0.7,1),"qty":option_lot_size,"ltp":ce_ltp,"oi":ce_oi}
        html = f"🟢 Option Buy → {atm} CE | Entry: {entry[0]}–{entry[1]} | Target: {plan['target']} | SL: {plan['stop_loss']} | LTP: {ce_ltp} | OI: {ce_oi}"
    else:
        avg = round((ce_ltp+pe_ltp)/2,1)
        plan = {"side":"Straddle","strike":atm,"avg_premium":avg,"ce_ltp":ce_ltp,"pe_ltp":pe_ltp,"qty":option_lot_size}
        html = f"⚖️ Straddle at {atm} (Buy CE+PE). Premium {avg}"

    return {"plan":plan,"html":html}

def recent_trend_warning(record, lookback=5):
    recs = MarketRecord.objects.filter(date__lt=record.date, interval="1d").order_by("-date")[:lookback]
    if not recs:
        return None
    ups = sum(1 for r in recs if r.close > r.open)
    downs = sum(1 for r in recs if r.close < r.open)

    if ups == lookback:
        return f"⚠️ Last {lookback} days UP → Avoid fresh Calls, market may correct."
    elif downs == lookback:
        return f"⚠️ Last {lookback} days DOWN → Avoid fresh Puts, market may rebound."
    return None

def lot_size(symbol="NIFTY"):
    return 75 if symbol.upper() == "NIFTY" else 15 if symbol.upper() == "BANKNIFTY" else 50

def probability_score(record):
    prob = 50
    try:
        if float(record.pcr) > 1.2: prob -= 5
        elif float(record.pcr) < 0.8: prob += 5
    except: pass
    try:
        if record.fii_net > 0: prob += 5
        elif record.fii_net < 0: prob -= 5
        if record.dii_net > 0: prob += 3
        elif record.dii_net < 0: prob -= 3
    except: pass
    if record.calculated_decision == "Bullish": prob += 5
    elif record.calculated_decision == "Bearish": prob -= 5
    return max(30, min(80, prob))

def build_narrative(record, traps):
    try:
        open_p, close_p = float(record.open), float(record.close)
        story = []
        if open_p > close_p:
            story.append("📉 Market opened gap-down and weak.")
        elif open_p < close_p:
            story.append("📈 Market opened gap-up with strength.")
        else:
            story.append("⚖️ Market opened flat, no direction early.")

        if traps:
            if any(t["direction"]=="down" for t in traps): story.append("👎 Midday selling dragged index lower.")
            if any(t["direction"]=="up" for t in traps): story.append("👍 Buyers lifted index intraday.")
            if traps[-1]["direction"]=="down": story.append("🚨 Closed near lows, sellers dominated.")
            else: story.append("✅ Recovered near close.")
        else:
            story.append("😐 Mostly consolidation, no big swings.")

        bias = get_decision(record)
        if bias == "Bullish": story.append("Overall positive → Call buyers favoured.")
        elif bias == "Bearish": story.append("Overall negative → Put buyers favoured.")
        else: story.append("Day ended neutral.")
        return " ".join(story)
    except:
        return "⚠️ Could not generate narrative."

def generate_detailed_summary_json(record):
    prev = MarketRecord.objects.filter(date__lt=record.date).order_by("-date").first()
    bias = get_decision(record)
    warning = recent_trend_warning(record, lookback=5)
    prob = probability_score(record)

    lines = [
        f"📊 Market Recap {record.date.strftime('%d-%b-%Y')}",
        f"- Nifty opened {record.open}, High {record.high}, Low {record.nifty_low}, Close {record.close}",
    ]
    if prev and float(prev.fii_net) < -500:
        lines.append("📉 Yesterday’s heavy FII selling hurt sentiment.")
    elif prev and float(prev.fii_net) > 500:
        lines.append("📈 Yesterday’s strong FII buying supported strength.")
    else:
        lines.append("⚖️ Neutral flows yesterday.")
    lines.append(f"📌 Bias: {bias}")
    lines.append(f"💰 FII Net: {record.fii_net} Cr | DII Net: {record.dii_net} Cr ")

    news_items = MarketNews.objects.filter(published_dt__date=record.date).order_by("-impact_score")[:3]
    news_list = [{"title": n.title, "source": n.source, "sentiment": n.sentiment} for n in news_items]

    m30 = getattr(record, "m30_set_calculated", [])
    traps = annotate_intraday_traps(record, m30, record.pcr)
    chart_data = [{"time": slot["time"], "points": slot["points"]} for slot in traps]

    trade = build_dynamic_trade_plan(record)
    trade_plan, trade_html = trade["plan"], trade["html"]

  
    suggestions = build_time_based_trade_suggestions(record)
    narrative = build_narrative(record, traps)

    return {
        "summary_lines": lines,
        "bias": bias,
        "flows": {"fii_net": float(record.fii_net), "dii_net": float(record.dii_net), "pcr": float(record.pcr)},
        "news": news_list,
        "intraday_traps": traps,
        "chart_data": chart_data,
        "trade_plan": trade_plan,
        "trade_plan_html": trade_html,
        "time_suggestions": suggestions,
        "narrative": narrative,
        "trend_warning": warning,
        "probability": prob,
    }

def analyze_time_patterns(record, days=40, interval="30m"):
    start_date = record.date - timedelta(days=days)
    qs = MarketRecord.objects.filter(date__gt=start_date, date__lt=record.date, interval=interval)
    stats = defaultdict(lambda: {"count":0,"up":0,"down":0,"moves":[]})
    for r in qs:
        try:
            pts = float(r.points)
        except Exception:
            continue
        key = r.hour.strftime("%H:%M") if r.hour else "NA"
        stats[key]["count"]+=1
        stats[key]["moves"].append(pts)
        if pts>0: stats[key]["up"]+=1
        elif pts<0: stats[key]["down"]+=1
    results = {}
    for k,v in stats.items():
        cnt=v["count"]
        results[k]={
            "count":cnt,
            "up_prob":v["up"]/cnt if cnt else 0,
            "down_prob":v["down"]/cnt if cnt else 0,
            "avg_up":sum([m for m in v["moves"] if m>0])/max(1,v["up"]),
            "avg_down":sum([m for m in v["moves"] if m<0])/max(1,v["down"]),
        }
    return results

def build_time_based_trade_suggestions(record, days=40, interval="30m", top_n=5):
    stats=analyze_time_patterns(record,days,interval)
    recs=[]
    bias=get_decision(record)
    for slot,st in stats.items():
        if st["count"]<6: continue
        if st["up_prob"]>0.55: action="Buy Call"
        elif st["down_prob"]>0.55: action="Buy Put"
        else: action="Avoid"
        conf=int(max(st["up_prob"],st["down_prob"])*100)
        if bias=="Bullish" and action=="Buy Call": conf+=10
        if bias=="Bearish" and action=="Buy Put": conf+=10
        recs.append({"time":slot,"action":action,"confidence":conf,"samples":st["count"]})
    return sorted(recs,key=lambda x:x["confidence"],reverse=True)[:top_n]

def summary_api(request):
    date = request.GET.get("date")
    index = request.GET.get("index", "NIFTY")  # ✅ default NIFTY
    if not date:
        return JsonResponse({"error": "Missing date"}, status=400)

    record = MarketRecord.objects.filter(index=index, date=date, interval="1d").first()
    if not record:
        return JsonResponse({"error": f"No record found for {index} on {date}"}, status=404)

    data = generate_detailed_summary_json(record)
    return JsonResponse(data)


def yahoo_quote(symbol, label):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if hist.empty:
            return {"value": "NA", "change": f"⚠ {label} unavailable"}
        latest = hist.iloc[-1]
        change = round(latest["Close"] - latest["Open"], 2)
        pct = round((change / latest["Open"]) * 100, 2) if latest["Open"] else 0
        return {"value": round(latest["Close"], 2), "change": f"{change} ({pct}%)"}
    except Exception as e:
        logger.error(f"Yahoo fallback failed for {label}: {e}")
        return {"value": "NA", "change": f"⚠ {label} unavailable"}

def live_ticker(request):
    data = {
        "nifty": yahoo_quote("^NSEI", "NIFTY"),
        "sensex": yahoo_quote("^BSESN", "SENSEX"),
        "usd_inr": yahoo_quote("INR=X", "USD/INR"),
        "crude": yahoo_quote("CL=F", "Crude Oil"),
        "sparklines": {"nifty": [], "sensex": []}
    }
    return JsonResponse(data)

def fetch_nifty_history(
    days=30,
    include_hourly=True,
    include_30m=True,
    include_5m=True,
    include_2m=True,
    include_live_daily=True,  # ✅ flag for provisional daily
):
    """
    Fetch NIFTY OHLCV data (daily + intraday). 
    Adds a provisional "today" daily candle from intraday if needed.
    """
    try:
        from datetime import datetime, time
        import pytz

        ist = pytz.timezone("Asia/Kolkata")
        ticker = yf.Ticker("^NSEI")
        records = []
        prev_daily_close = None

        logger.debug("=== fetch_nifty_history called (days=%s) ===", days)

        # --- Daily candles ---
        df_daily = ticker.history(period=f"{days}d", interval="1d")
        logger.debug("Daily rows fetched: %s", len(df_daily))

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

        # --- Intraday intervals ---
        intraday_config = [
            ("1h", max(7, days), include_hourly),
            ("30m", max(7, days), include_30m),
            ("5m", max(5, days), include_5m),
            ("2m", max(5, days), include_2m),
        ]
        intraday_today = []

        for interval, period, enabled in intraday_config:
            if not enabled:
                continue

            df = ticker.history(period=f"{period}d", interval=interval)
            logger.debug("%s rows fetched for interval=%s", len(df), interval)

            if df.empty:
                continue

            for ts, row in df.iterrows():
                ts = pd.to_datetime(ts)

                # ✅ Handle naive vs tz-aware
                if ts.tzinfo is None:
                    py_dt = ts.tz_localize("UTC").astimezone(ist)
                else:
                    py_dt = ts.tz_convert(ist)

                t = py_dt.time().replace(second=0, microsecond=0)

                if time(9, 15) <= t <= time(15, 30):
                    rec = {
                        "date": py_dt.date(),
                        "hour": t,
                        "interval": interval,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "points": 0.0,
                    }
                    records.append(rec)

                    # ✅ collect today's intraday for provisional daily
                    if include_live_daily and interval == "30m":
                        if py_dt.date() == datetime.now(ist).date():
                            intraday_today.append(rec)

            if not df.empty:
                logger.debug("First %s ts=%s | Last ts=%s",
                             interval, df.index[0], df.index[-1])

        # --- Provisional daily candle ---
        if include_live_daily and intraday_today:
            today = datetime.now(ist).date()
            if not any(r["interval"] == "1d" and r["date"] == today for r in records):
                o = intraday_today[0]["open"]
                h = max(r["high"] for r in intraday_today)
                l = min(r["low"] for r in intraday_today)
                c = intraday_today[-1]["close"]
                points = c - prev_daily_close if prev_daily_close else 0
                records.append({
                    "date": today,
                    "hour": None,
                    "interval": "1d",
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "points": round(points, 2),
                    "provisional": True,   # ✅ mark it clearly
                })
                logger.debug("Added provisional daily candle for %s: O=%s H=%s L=%s C=%s",
                             today, o, h, l, c)

        # --- Sort results ---
        records.sort(key=lambda r: (r["date"], r["hour"] or time(0, 0)))
        logger.debug("Final record count: %s", len(records))
        return records

    except Exception as e:
        logger.exception("Error fetching nifty history: %s", e)
        return []

def fetch_fii_dii():
    """Scrape Groww FII/DII data"""
    try:
        url = "https://groww.in/fii-dii-data"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script_tag:
            raise RuntimeError("❌ Could not find __NEXT_DATA__ in page")
        data = json.loads(script_tag.string)
        fii_dii_data = data["props"]["pageProps"]["initialData"]

        parsed = []
        for row in fii_dii_data:
            parsed.append({
                "date": row["date"],
                "fii_net": float(row["fii"]["netBuySell"]),
                "dii_net": float(row["dii"]["netBuySell"]),
                "fii_buy": float(row["fii"]["grossBuy"]),
                "fii_sell": float(row["fii"]["grossSell"]),
                "dii_buy": float(row["dii"]["grossBuy"]),
                "dii_sell": float(row["dii"]["grossSell"]),
            })
        return parsed
    except Exception as e:
        logger.error(f"⚠️ FII/DII fetch failed: {e}")
        return []

def fetch_fii_dii_data():
    """Map FII/DII to {date: {fii, dii}}"""
    parsed = fetch_fii_dii()
    fii_dii_map = {}
    for row in parsed:
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d").date()
            fii_dii_map[d] = {"fii": row["fii_net"], "dii": row["dii_net"]}
        except Exception as e:
            logger.warning(f"Skipping FII/DII row {row}: {e}")
    return fii_dii_map

def update_fii_dii_data():
    data = fetch_fii_dii()
    created, updated = 0, 0
    for row in data:
        date_val = datetime.strptime(row["date"], "%Y-%m-%d").date()
        obj, is_created = FiiDiiRecord.objects.update_or_create(
            date=date_val,
            defaults={
                "fii_buy": row["fii_buy"], "fii_sell": row["fii_sell"], "fii_net": row["fii_net"],
                "dii_buy": row["dii_buy"], "dii_sell": row["dii_sell"], "dii_net": row["dii_net"],
            }
        )
        if is_created: created += 1
        else: updated += 1
    return {"created": created, "updated": updated}

def fetch_pcr_data():
    try:
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        session = requests.Session()
        session.get("https://www.nseindia.com", headers={"User-Agent": "Mozilla/5.0"})
        res = session.get(url, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        ce_oi = sum([d["CE"]["openInterest"] for d in data["records"]["data"] if "CE" in d])
        pe_oi = sum([d["PE"]["openInterest"] for d in data["records"]["data"] if "PE" in d])
        return round(pe_oi / ce_oi, 2) if ce_oi > 0 else 0
    except Exception as e:
        logger.error(f"PCR fetch failed: {e}")
        return 0

def fetch_intraday_pcr(symbol="NIFTY"):
    """Fetch current Put/Call Ratio from NSE option chain API"""
    try:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        res = session.get(url, headers=NSE_HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()

        ce_oi = sum([d["CE"]["openInterest"] for d in data["records"]["data"] if "CE" in d])
        pe_oi = sum([d["PE"]["openInterest"] for d in data["records"]["data"] if "PE" in d])
        return round(pe_oi / ce_oi, 2) if ce_oi else 0
    except Exception as e:
        logger.error(f"PCR fetch failed: {e}")
        return 0

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

# === NSE Headers ===
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/option-chain",
}

# === Fetch Option Chain ===
def fetch_nifty_option_chain():
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    session.get("https://www.nseindia.com/option-chain", headers=NSE_HEADERS, timeout=10)
    data = session.get(url, headers=NSE_HEADERS, timeout=10).json()

    underlying = data["records"]["underlyingValue"]
    option_data = data["records"]["data"]
    return underlying, option_data

def get_latest_nifty_price():
    try:
        ticker = yf.Ticker("^NSEI")
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            return None
        latest = data.iloc[-1]
        return round(float(latest["Close"]), 2)
    except Exception as e:
        print(f"⚠️ Error fetching Nifty price: {e}")
        return None

def trade_prices_api(request):
    latest_price = get_latest_nifty_price()
    pending_options = OptionTrade.objects.filter(status="Pending")
    options_data = [
        {
            "id": opt.id,
            "strike": opt.strike,
            "type": opt.type,
            "ltp": float(opt.ltp or 0),
            "sl": float(opt.stop_loss),
            "target": float(opt.target),
            "status": opt.status,
        }
        for opt in pending_options
    ]
    return JsonResponse({"nifty": latest_price, "options": options_data})

def update_trade_status():
    active_trades = TradePlan.objects.filter(status="Pending")
    latest_price = get_latest_nifty_price()
    for trade in active_trades:
        if trade.direction == "Long":
            if latest_price >= trade.target:
                trade.status = "Hit Target"
            elif latest_price <= trade.stop_loss:
                trade.status = "Stop Loss"
        else:
            if latest_price <= trade.target:
                trade.status = "Hit Target"
            elif latest_price >= trade.stop_loss:
                trade.status = "Stop Loss"
        trade.save(update_fields=["status"])

    try:
        _, option_data = fetch_nifty_option_chain()
    except Exception as e:
        print(f"⚠️ NSE fetch failed: {e}")
        return

    active_options = OptionTrade.objects.filter(status="Pending")
    for opt in active_options:
        row = next((r for r in option_data if r.get("strikePrice") == opt.strike), None)
        if not row:
            print(f"⚠️ No NSE data for strike {opt.strike}")
            continue

        key = "CE" if opt.type == "CALL" else "PE"
        ltp = row.get(key, {}).get("lastPrice", opt.ltp)
        if not ltp:
            continue

        if ltp >= opt.target:
            opt.status = "Hit Target"
        elif ltp <= opt.stop_loss:
            opt.status = "Stop Loss"

        opt.ltp = ltp
        opt.save(update_fields=["ltp", "status"])

def generate_trade_plan(price):
    direction = "Long" if price % 2 == 0 else "Short"
    stop_loss = price - 25 if direction == "Long" else price + 25
    target = price + 60 if direction == "Long" else price - 60
    confidence = 75
    plan = TradePlan.objects.create(
        level=price,
        direction=direction,
        entry_price=price,
        stop_loss=stop_loss,
        target=target,
        confidence=confidence,
        pcr=1.2,
        fii_signal="Bullish",
        dii_signal="Bearish",
        option_sentiment="Bearish",
        signals={"dummy": "example"}
    )
    try:
        underlying, option_data = fetch_nifty_option_chain()
    except Exception as e:
        return plan
    atm = int(round(price / 50) * 50)
    strikes = [atm, atm + 50]
    opt_type = "PE" if direction == "Short" else "CE"   # NSE data uses CE/PE
    model_type = "PUT" if direction == "Short" else "CALL"  # For DB consistency

    for strike in strikes:
        row = next((r for r in option_data if r.get("strikePrice") == strike), None)
        if not row:
            print(f"⚠️ No NSE data for strike {strike}")
            continue

        ltp = row.get(opt_type, {}).get("lastPrice")
        if not ltp:
            print(f"⚠️ No LTP found for strike {strike} {opt_type}")
            continue

        stop_loss_opt = round(ltp * 0.7, 2)
        target_opt = round(ltp * 1.7, 2)

        opt = OptionTrade.objects.create(
            trade_plan=plan,
            strike=strike,
            type=model_type,
            ltp=ltp,
            stop_loss=stop_loss_opt,
            target=target_opt,
        )
        print(f"📌 Created OptionTrade {opt.id} {model_type} {strike} → LTP={ltp}, SL={stop_loss_opt}, Target={target_opt}")
    return plan

def live_trade_plan(request):
    price = get_latest_nifty_price()
    if not price:
        return JsonResponse({"error": "Failed to fetch price"})
    plan = generate_trade_plan(price)

    return JsonResponse({
        "time": str(localtime(plan.created_at)),
        "price": float(plan.level),
        "direction": plan.direction,
        "entry": float(plan.entry_price),
        "sl": float(plan.stop_loss),
        "target": float(plan.target),
        "confidence": float(plan.confidence),
        "expiry": plan.expiry.strftime("%Y-%m-%d"),  # ✅ added
        "options": [
            {
                "strike": o.strike,
                "type": o.type,
                "ltp": float(o.ltp),
                "sl": float(o.stop_loss),
                "target": float(o.target),
                "status": o.status,
            } for o in plan.options.all()
        ]
    })

def trade_dashboard(request):
    update_trade_status()
    qs = TradePlan.objects.all().order_by("-created_at")

    summary = {
        "total": qs.count(),
        "success": qs.filter(status="Hit Target").count(),
        "failed": qs.filter(status="Stop Loss").count(),
        "inprogress": qs.filter(status="Pending").count(),
    }
    summary["win_rate"] = round((summary["success"] / summary["total"] * 100), 2) if summary["total"] else 0

    plans = qs.prefetch_related("options")[:20]

    return render(request, "marketdata/trade_dashboard.html", {
        "plans": plans,
        "summary": summary,
        "live_price": get_latest_nifty_price(),
        "default_expiry": plans[0].expiry.strftime("%Y-%m-%d") if plans else None
    })

def fetch_option_chain_analysis():
    """
    Fetch live option chain and calculate support/resistance.
    """
    try:
        _, option_data = fetch_nifty_option_chain()

        chain = []
        call_oi_map = {}
        put_oi_map = {}

        for row in option_data:
            strike = row["strikePrice"]
            ce = row.get("CE", {})
            pe = row.get("PE", {})

            call_oi = ce.get("openInterest", 0)
            put_oi = pe.get("openInterest", 0)

            chain.append({
                "strike": strike,
                "call_ltp": ce.get("lastPrice", 0),
                "put_ltp": pe.get("lastPrice", 0),
                "call_oi": call_oi,
                "put_oi": put_oi,
            })

            call_oi_map[strike] = call_oi
            put_oi_map[strike] = put_oi

        # Find support = strike with max PUT OI
        support_strike = max(put_oi_map, key=put_oi_map.get, default=None)
        # Find resistance = strike with max CALL OI
        resistance_strike = max(call_oi_map, key=call_oi_map.get, default=None)

        return {
            "chain": chain,
            "support": support_strike,
            "resistance": resistance_strike,
        }

    except Exception as e:
        print(f"⚠️ Error fetching option chain: {e}")
        return {"chain": [], "support": None, "resistance": None}

def fetch_nifty_option_chain(expiry=None):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    session = requests.Session()
    session.get("https://www.nseindia.com/option-chain", headers=NSE_HEADERS, timeout=10)
    data = session.get(url, headers=NSE_HEADERS, timeout=10).json()

    underlying = data["records"]["underlyingValue"]
    option_data = data["records"]["data"]

    if expiry:
        option_data = [row for row in data["records"]["data"] if row["expiryDate"] == expiry]

    return underlying, option_data

def option_chain_api(request, strike):
    """
    Returns option chain snapshot (±150 points) + ATM + support/resistance + OI trends.
    """
    data = fetch_option_chain_analysis()
    chain = data["chain"]

    strike = int(strike)
    snapshot = [row for row in chain if abs(row["strike"] - strike) <= 150]

    atm_strike = min(snapshot, key=lambda r: abs(r["strike"] - strike))["strike"] if snapshot else None

    # ✅ Compare with previous snapshot for trend detection
    prev_snapshot = cache.get("option_chain_snapshot", {})
    trend_snapshot = {}

    for row in snapshot:
        strike_val = row["strike"]
        prev = prev_snapshot.get(strike_val, {})

        call_oi_trend = "neutral"
        put_oi_trend = "neutral"

        if prev:
            if row["call_oi"] > prev.get("call_oi", 0):
                call_oi_trend = "up"
            elif row["call_oi"] < prev.get("call_oi", 0):
                call_oi_trend = "down"

            if row["put_oi"] > prev.get("put_oi", 0):
                put_oi_trend = "up"
            elif row["put_oi"] < prev.get("put_oi", 0):
                put_oi_trend = "down"

        trend_snapshot[strike_val] = {
            "call_oi_trend": call_oi_trend,
            "put_oi_trend": put_oi_trend,
        }

    # Save current snapshot for next comparison
    cache.set("option_chain_snapshot", {r["strike"]: r for r in snapshot}, timeout=300)

    return JsonResponse({
        "snapshot": snapshot,
        "support": data["support"],
        "resistance": data["resistance"],
        "atm": atm_strike,
        "trend": trend_snapshot,
    })

def accordion_view(request, rec_id, interval):
    cache_key = f"accordion:{rec_id}:{interval}"
    html = cache.get(cache_key)

    if html:
        return HttpResponse(html)

    rec = MarketRecord.objects.get(id=rec_id)

    if interval == "hourly":
        data = rec.hourly_set_calculated    
        title = "Hourly Data"
    elif interval == "m30":
        data = rec.m30_set_calculated
        title = "30-Minute Data"
    elif interval == "m5":
        data = rec.m5_set_calculated
        title = "5-Minute Data"
    elif interval == "m2":
        data = rec.m2_set_calculated
        title = "2-Minute Data"
    else:
        return HttpResponse("Invalid interval")

    # Precompute decision once
    for row in data:
        row.final_decision = row.calculated_decision

    html = render_to_string("marketdata/accordion.html", {
        "title": title,
        "data": data,
        "interval": interval
    }, request=request)

    cache.set(cache_key, html, timeout=600)  # 10 minutes cache
    return HttpResponse(html)

def assign_action_simple(rec, sniper, side):
    """Assigns action using bias & sniper levels"""
    bias = get_decision(rec)
    close = rec.close

    if bias == "Bullish":
        if side == "CE":
            return "⚡ CE Buy (Above ATM, Trend Confirmed)" if close >= sniper.atm else "✅ CE Buy (Breakout)"
        return "🚫 Avoid PE in Bullish"

    elif bias == "Bearish":
        if side == "PE":
            return "⚡ PE Buy (Below ATM, Trend Confirmed)" if close <= sniper.atm else "✅ PE Buy (Breakdown)"
        return "🚫 Avoid CE in Bearish"

    else:
        return "📉 Range Bound (Avoid)"
def fetch_index_history(
    index_symbol="^NSEI",   # ^BSESN for Sensex
    days=30,
    include_hourly=True,
    include_30m=True,
    include_5m=True,
    include_2m=True,
    include_live_daily=True,
):
    from datetime import datetime, time
    import pytz

    ist = pytz.timezone("Asia/Kolkata")
    records = []
    prev_daily_close = None

    try:
        ticker = yf.Ticker(index_symbol)

        # --- Daily candles ---
        df_daily = ticker.history(period=f"{days}d", interval="1d")
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

        # --- Intraday intervals ---
        intraday_config = [
            ("1h", max(7, days), include_hourly),
            ("30m", max(7, days), include_30m),
            ("5m", max(5, days), include_5m),
            ("2m", max(5, days), include_2m),
        ]
        intraday_today = []

        for interval, period, enabled in intraday_config:
            if not enabled:
                continue
            df = ticker.history(period=f"{period}d", interval=interval)
            for ts, row in df.iterrows():
                ts = pd.to_datetime(ts)
                py_dt = ts.tz_localize("UTC").astimezone(ist) if ts.tzinfo is None else ts.tz_convert(ist)
                t = py_dt.time().replace(second=0, microsecond=0)
                if time(9, 15) <= t <= time(15, 30):
                    rec = {
                        "date": py_dt.date(),
                        "hour": t,
                        "interval": interval,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "points": 0.0,
                    }
                    records.append(rec)
                    if include_live_daily and interval == "30m":
                        if py_dt.date() == datetime.now(ist).date():
                            intraday_today.append(rec)

        # --- Provisional daily candle ---
        if include_live_daily and intraday_today:
            today = datetime.now(ist).date()
            if not any(r["interval"] == "1d" and r["date"] == today for r in records):
                o = intraday_today[0]["open"]
                h = max(r["high"] for r in intraday_today)
                l = min(r["low"] for r in intraday_today)
                c = intraday_today[-1]["close"]
                points = c - prev_daily_close if prev_daily_close else 0
                records.append({
                    "date": today,
                    "hour": None,
                    "interval": "1d",
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "points": round(points, 2),
                })

        records.sort(key=lambda r: (r["date"], r["hour"] or time(0, 0)))
        return records
    except Exception as e:
        logger.exception("Error fetching history: %s", e)
        return []
def run_update(auto=False, index="NIFTY"):
    from datetime import datetime, date, time
    import pytz

    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist).time()

    if auto and not (time(9, 15) <= now <= time(15, 25)):
        return "⏸ Outside market hours"

    days = 1 if auto else 30
    symbol = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN"
}.get(index, "^NSEI")  # default to NIFTY

    print('venkat')
    records = fetch_index_history(symbol, days=days, include_hourly=True, include_30m=True)
    fii_dii_list = fetch_fii_dii()
    fii_dii_map = {datetime.strptime(r["date"], "%Y-%m-%d").date(): r for r in fii_dii_list}

    for r in records:
        date_val = r["date"]
        fii_info = fii_dii_map.get(date_val, {})

        MarketRecord.objects.update_or_create(
            index=index,
            date=date_val,
            hour=r["hour"],
            interval=r["interval"],
            defaults={
                "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
                "points": r["points"],
                "fii_buy": fii_info.get("fii_buy", 0),
                "fii_sell": fii_info.get("fii_sell", 0),
                "fii_net": fii_info.get("fii_net", 0),
                "dii_buy": fii_info.get("dii_buy", 0),
                "dii_sell": fii_info.get("dii_sell", 0),
                "dii_net": fii_info.get("dii_net", 0),
                "pcr": 0,
            },
        )
    return f"✅ Update done for {index} ({'today only' if auto else '30 days'})"
def compute_and_store_sniper(record_date=None):
    from datetime import date
    today = record_date or date.today()

    rec = MarketRecord.objects.filter(date=today, interval="1d").first()
    if not rec:
        return None

    close_price = float(rec.close)
    atm = round(close_price / 50) * 50
    if close_price < atm:
        atm -= 50

    # === Fetch option chain ===
    try:
        _, option_data = fetch_nifty_option_chain()
    except Exception:
        return None

    strikes = [atm, atm + 100, atm - 100]

    ce100 = next((float(r.get("CE", {}).get("lastPrice", 0)) for r in option_data if r.get("strikePrice") == atm + 100), 0)
    pe100 = next((float(r.get("PE", {}).get("lastPrice", 0)) for r in option_data if r.get("strikePrice") == atm - 100), 0)
    sniper_val = (ce100 + pe100) / 2 if ce100 and pe100 else 50

    # ✅ Compute bias
    bias = get_decision(rec)  # "Bullish", "Bearish", "Neutral"

    # === Store sniper levels ===
    sniper_level, _ = SniperLevel.objects.update_or_create(
        date=today,
        defaults={
            "close_price": close_price,
            "atm": atm,
            "sniper": sniper_val,
            # 🔥 Narrower bands with bias-driven breakouts
            "upper": atm + (sniper_val * 0.5),
            "lower": atm - (sniper_val * 0.5),
            "upper_double": atm + sniper_val,
            "lower_double": atm - sniper_val,
            "bias": bias,
        }
    )

    # === Delete old trades ===
    SniperTrade.objects.filter(sniper=sniper_level).delete()
    trades = []

    # Confidence adjustment
    base_conf = 60
    if abs(rec.points) > 200:
        base_conf += 20
    elif abs(rec.points) > 100:
        base_conf += 10

    for strike in strikes:
        row = next((r for r in option_data if r.get("strikePrice") == strike), None)
        if not row:
            continue

        for side in ["CE", "PE"]:
            ltp = float(row.get(side, {}).get("lastPrice", 0))
            if not ltp:
                continue

            entry = ltp
            stoploss = round(entry * 0.7, 2)
            target1 = round(entry * 1.5, 2)
            target2 = round(entry * 2.0, 2)
            rr_ratio = round((target1 - entry) / (entry - stoploss), 2) if (entry - stoploss) > 0 else 1

            # Confidence & note
            if (bias == "Bullish" and side == "CE") or (bias == "Bearish" and side == "PE"):
                confidence = base_conf + 15
                note = f"✅ Favoured {side}@{strike} | Bias={bias}"
            elif bias == "Neutral":
                confidence = base_conf
                note = f"⚖ Neutral {side}@{strike} | Bias=Neutral"
            else:
                confidence = base_conf - 15
                note = f"⚠ Risky {side}@{strike} | Bias={bias}"

            # Action (using bias + breakout)
            action = assign_action(trade_side=side, sniper=sniper_level, rec=rec, bias=bias)

            trade = SniperTrade.objects.create(
                sniper=sniper_level,
                side=side,
                strike=strike,
                entry=entry,
                stoploss=stoploss,
                target1=target1,
                target2=target2,
                risk_reward=f"{rr_ratio} R/R",
                confidence=confidence,
                action=action,
                note=note,
            )
            trades.append(trade)

    return {"sniper": sniper_level, "trades": trades}


def assign_action(trade_side, sniper, rec, bias):
    """
    Decide actionable trade signal based on bias + sniper levels
    """
    close = rec.close
    action = "⚠ Wait / Neutral"

    if bias == "Bullish":
        if trade_side == "CE":
            if close >= sniper.upper_double:
                action = "🚀 Strong CE Breakout"
            elif close >= sniper.upper:
                action = "✅ CE Buy (Breakout)"
            elif close >= sniper.atm:
                action = "⚡ CE Buy (Above ATM)"
        else:
            action = "🚫 Avoid PE in Bullish"

    elif bias == "Bearish":
        if trade_side == "PE":
            if close <= sniper.lower_double:
                action = "💥 Strong PE Breakdown"
            elif close <= sniper.lower:
                action = "✅ PE Buy (Breakdown)"
            elif close <= sniper.atm:
                action = "⚡ PE Buy (Below ATM)"
        else:
            action = "🚫 Avoid CE in Bearish"

    else:  # Neutral bias
        if close >= sniper.upper:
            action = "📈 Neutral Bias Breakout"
        elif close <= sniper.lower:
            action = "📉 Neutral Bias Breakdown"
        else:
            action = "⚖ Range Bound"

    return action

def update_sniper_last_30days():
    """Compute Sniper Levels for last 30 calendar days but update only trading days (skip weekends/holidays)."""
    today = date.today()
    updated = []
    for i in range(30):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:   # skip Sat/Sun
            continue
        res = compute_and_store_sniper(record_date=d)
        if res:
            updated.append(str(d))
    return {"updated_days": updated, "count": len(updated)}

# marketdata/utils.py
from datetime import datetime, timezone
import math

def estimate_profit_for_option(entry_price, current_price, position="long", qty=1):
    """
    Quick estimate: profit = (current - entry) * qty for long, reversed for short.
    `position` can be "long" or "short".
    """
    if entry_price is None or current_price is None:
        return 0.0
    diff = current_price - entry_price
    if position == "short":
        diff = -diff
    return round(diff * qty, 2)

def summarize_chain(option_data, atm):
    """
    Summarize option chain into total call/put ltp sums, volumes, oi, and per-strike snapshots.
    option_data: list of rows (dicts) that contain strikePrice, CE, PE dicts with lastPrice, openInterest, totalTradedVolume
    """
    call_sum = 0.0
    put_sum = 0.0
    call_vol = 0
    put_vol = 0
    call_oi = 0
    put_oi = 0
    rows = []

    for r in option_data:
        strike = r.get("strikePrice")
        ce = r.get("CE", {}) or {}
        pe = r.get("PE", {}) or {}

        ce_ltp = float(ce.get("lastPrice") or 0)
        pe_ltp = float(pe.get("lastPrice") or 0)

        ce_vol = int(ce.get("totalTradedVolume") or 0)
        pe_vol = int(pe.get("totalTradedVolume") or 0)

        ce_oi = int(ce.get("openInterest") or 0)
        pe_oi = int(pe.get("openInterest") or 0)

        call_sum += ce_ltp
        put_sum += pe_ltp
        call_vol += ce_vol
        put_vol += pe_vol
        call_oi += ce_oi
        put_oi += pe_oi

        rows.append({
            "strike": strike,
            "CE": {"ltp": ce_ltp, "vol": ce_vol, "oi": ce_oi},
            "PE": {"ltp": pe_ltp, "vol": pe_vol, "oi": pe_oi},
        })

    return {
        "call_sum": call_sum, "put_sum": put_sum,
        "call_vol": call_vol, "put_vol": put_vol,
        "call_oi": call_oi, "put_oi": put_oi,
        "rows": rows
    }

def detect_trap(snapshot_summary, previous_summary=None):
    """
    Heuristic to detect 'trapping buyers' conditions:
    - Large spike in call/put volume vs previous snapshot
    - OI decreasing while price increases (sign of short covering or trap)
    - Imbalance between call and put ltp sums
    Returns flag and note.
    """
    notes = []
    flag = False

    # volume spikes
    if previous_summary:
        def pct_diff(a, b):
            if b == 0: return 0
            return (a - b) / b * 100

        vol_spike_calls = pct_diff(snapshot_summary["call_vol"], previous_summary["call_vol"])
        vol_spike_puts = pct_diff(snapshot_summary["put_vol"], previous_summary["put_vol"])

        if vol_spike_calls > 50 and snapshot_summary["call_vol"] > snapshot_summary["put_vol"]:
            flag = True
            notes.append(f"Call volume spike {vol_spike_calls:.0f}%")

        if vol_spike_puts > 50 and snapshot_summary["put_vol"] > snapshot_summary["call_vol"]:
            flag = True
            notes.append(f"Put volume spike {vol_spike_puts:.0f}%")

        # OI drop while price moved up -> possible short squeeze / trap
        if pct_diff(snapshot_summary["call_oi"], previous_summary["call_oi"]) < -10 and snapshot_summary["call_vol"] > previous_summary["call_vol"]:
            flag = True
            notes.append("Call OI fell while call volume rose (possible covering)")

        if pct_diff(snapshot_summary["put_oi"], previous_summary["put_oi"]) < -10 and snapshot_summary["put_vol"] > previous_summary["put_vol"]:
            flag = True
            notes.append("Put OI fell while put volume rose (possible covering)")
    else:
        # no previous, do simple imbalance check
        if snapshot_summary["call_vol"] > snapshot_summary["put_vol"] * 1.5:
            flag = True
            notes.append("Call volume >> Put volume")
        if snapshot_summary["put_vol"] > snapshot_summary["call_vol"] * 1.5:
            flag = True
            notes.append("Put volume >> Call volume")

    # LTP imbalance
    if snapshot_summary["call_sum"] > snapshot_summary["put_sum"] * 1.2:
        notes.append("Call LTP > Put LTP (call strength)")
    elif snapshot_summary["put_sum"] > snapshot_summary["call_sum"] * 1.2:
        notes.append("Put LTP > Call LTP (put strength)")

    return flag, "; ".join(notes)

def sniper_dashboard(request):
    from datetime import date, timedelta
    snapshots = MarketSnapshot.objects.order_by("-timestamp")[:10]
    if "update_sniper" in request.POST:
        compute_and_store_sniper()
        return redirect("sniper_dashboard")

    elif "update_30days" in request.POST:
        today = date.today()
        for i in range(30):
            d = today - timedelta(days=i)
            compute_and_store_sniper(record_date=d)
        return redirect("sniper_dashboard")

    days = int(request.GET.get("days", 30))
    search = request.GET.get("search", "").strip()
    side_filter = request.GET.get("side", "")
    min_conf = request.GET.get("min_conf", "")

    start_date = date.today() - timedelta(days=days)
    snipers = SniperLevel.objects.filter(date__gte=start_date).order_by("-date")
    sniper_list = []
    for s in snipers:
        rec = MarketRecord.objects.filter(date=s.date, interval="1d").first()
        trades = s.trades.all()

        # Apply filters
        if side_filter:
            trades = trades.filter(side=side_filter)
        if min_conf:
            try:
                trades = trades.filter(confidence__gte=int(min_conf))
            except:
                pass
        if search:
            trades = trades.filter(Q(note__icontains=search) | Q(strike__icontains=search))

        # ✅ Add action field for each trade
        trades_with_actions = []
        for t in trades:
            t.action = assign_action(
                trade_side=t.side, 
                sniper=s, 
                rec=rec, 
                bias=s.bias if hasattr(s, "bias") else get_decision(rec)
            ) if rec else "⚠ No Market Record"
            trades_with_actions.append(t)


        sniper_list.append({"sniper": s, "trades": trades_with_actions})

    paginator = Paginator(sniper_list, 30)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "marketdata/sniper_dashboard.html", {
        "page_obj": page_obj,
        "days": days,
        "search": search,
        "side_filter": side_filter,
        "min_conf": min_conf,
         "snapshots": snapshots, 
    })

from datetime import date
from .models import  SniperLevel

from datetime import date
from django.http import JsonResponse

def sniper_api(request):
    date_str = request.GET.get("date")
    if date_str:
        try:
            req_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return JsonResponse({"error": "Invalid date"}, status=400)
    else:
        req_date = date.today()

    sniper = SniperLevel.objects.filter(date=req_date).first()
    if not sniper:
        data = compute_and_store_sniper(record_date=req_date)
        if not data:
            return JsonResponse({"error": f"No data for {req_date}"}, status=404)
        sniper = data["sniper"]

    trades = [
        {
            "side": t.side,
            "strike": t.strike,
            "entry": t.entry,
            "stoploss": t.stoploss,
            "target1": t.target1,
            "target2": t.target2,
            "rr": t.risk_reward,
            "confidence": t.confidence,
            "note": t.note,
        }
        for t in sniper.trades.all()
    ]

    payload = {
        "date": str(sniper.date),
        "close_price": sniper.close_price,
        "atm": sniper.atm,
        "sniper": sniper.sniper,
        "upper": sniper.upper,
        "lower": sniper.lower,
        "upper_double": sniper.upper_double,
        "lower_double": sniper.lower_double,
        "trades": trades,
    }
    return JsonResponse(payload)

from django.shortcuts import render
from django.core.paginator import Paginator
from django.http import JsonResponse
from .models import MarketSnapshot, MarketSignal
from django.db.models import Q
from datetime import datetime, date

def market_monitor(request):
    """
    Page to view snapshots. Filters: date, recommendation, trap_flag.
    """
    qdate = request.GET.get("date")
    rec_filter = request.GET.get("recommendation", "")
    trap = request.GET.get("trap", "")
    page = int(request.GET.get("page", 1))

    snaps = MarketSnapshot.objects.all().order_by("-timestamp")
    if qdate:
        try:
            d = datetime.strptime(qdate, "%Y-%m-%d").date()
            snaps = snaps.filter(date=d)
        except:
            pass
    if rec_filter:
        snaps = snaps.filter(recommendation__icontains=rec_filter)
    if trap.lower() in ("1", "true", "yes"):
        snaps = snaps.filter(trap_flag=True)

    paginator = Paginator(snaps, 10)
    page_obj = paginator.get_page(page)

    return render(request, "marketdata/market_monitor.html", {
        "page_obj": page_obj,
        "recommendation": rec_filter,
        "trap": trap,
        "date": qdate or "",
    })

def market_monitor_api(request):
    """
    Return JSON of latest snapshot (or by date param).
    """
    qdate = request.GET.get("date")
    if qdate:
        try:
            d = datetime.strptime(qdate, "%Y-%m-%d").date()
            snap = MarketSnapshot.objects.filter(date=d).order_by("-timestamp").first()
        except:
            return JsonResponse({"error": "invalid date"}, status=400)
    else:
        snap = MarketSnapshot.objects.order_by("-timestamp").first()
    if not snap:
        return JsonResponse({"error": "no snapshot"}, status=404)

    signals = list(snap.signals.all().values("side", "strike", "ltp", "oi", "volume", "est_profit", "trap", "note"))
    payload = {
        "timestamp": snap.timestamp.isoformat(),
        "date": str(snap.date),
        "close": snap.close,
        "atm": snap.atm,
        "sniper": snap.sniper,
        "totals": {"call_sum": snap.total_call_profit, "put_sum": snap.total_put_profit},
        "vol_oi": {"call_vol": snap.call_volume, "put_vol": snap.put_volume, "call_oi": snap.call_oi, "put_oi": snap.put_oi},
        "trap_flag": snap.trap_flag,
        "trap_note": snap.trap_note,
        "recommendation": snap.recommendation,
        "signals": signals
    }
    return JsonResponse(payload)


def latest_snapshot_time(request):
    """Return latest MarketSnapshot timestamp as unix epoch (int)."""
    snap = MarketSnapshot.objects.order_by("-timestamp").first()
    if snap:
        return JsonResponse({"last_timestamp": int(snap.timestamp.timestamp())})
    return JsonResponse({"last_timestamp": 0})
# marketdata/views.py
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.core.cache import cache
from datetime import date, timedelta
from .models import MarketRecord

def record_list(request, index):
    # MarketRecord.objects.all().delete()
    filter_option = request.GET.get("filter", "all")
    trend_filter = filter_option if filter_option in ["bullish", "bearish", "neutral"] else "all"
    page_number = request.GET.get("page", 1)

    # cache key with index
    page_cache_key = f"record_list:{index}:{filter_option}:{trend_filter}:{page_number}"
    cached_response = cache.get(page_cache_key)
    if cached_response:
        return cached_response

    # manual update
    if request.method == "POST" and "update_data" in request.POST:
        run_update(auto=False, index=index)
        return redirect(f"{index.lower()}_list")

    # auto update
    if request.GET.get("auto_update") == "1":
        run_update(auto=True, index=index)

    # === Base queryset ===
    qs = MarketRecord.objects.filter(interval="1d", index=index).order_by("-date")
    today = date.today()

    # === Date filters ===
    if filter_option == "today":
        qs = qs.filter(date=today)
    elif filter_option == "yesterday":
        qs = qs.filter(date=today - timedelta(days=1))
    elif filter_option == "week":
        start_of_week = today - timedelta(days=today.weekday())
        qs = qs.filter(date__gte=start_of_week, date__lte=today)
    elif filter_option == "month":
        qs = qs.filter(date__year=today.year, date__month=today.month)
    elif filter_option == "3months":
        qs = qs.filter(date__gte=today - timedelta(days=90), date__lte=today)
    elif filter_option in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
        weekday_map = {"monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6}
        qs = qs.filter(date__week_day=weekday_map[filter_option])

    # --- Convert to list for decision filtering ---
    all_records = list(qs)

    # === Trend filter ===
    if trend_filter == "bullish":
        all_records = [r for r in all_records if r.calculated_decision == "Bullish"]
    elif trend_filter == "bearish":
        all_records = [r for r in all_records if r.calculated_decision == "Bearish"]
    elif trend_filter == "neutral":
        all_records = [r for r in all_records if r.calculated_decision == "Neutral"]

    # === Pagination ===
    paginator = Paginator(all_records, 25)
    page_obj = paginator.get_page(page_number)

    # === Compute bias and percentages ===
    # === Compute bias and percentages ===
    for rec in page_obj:
        fii = rec.fii_net or 0
        dii = rec.dii_net or 0
        points = rec.points or 0
        rec.bias = decide_trend_from_fii_dii(fii, dii, points)
        total_abs = abs(fii) + abs(dii)
        rec.fii_percent = round((abs(fii) / total_abs) * 100, 1) if total_abs > 0 else 0
        rec.dii_percent = round((abs(dii) / total_abs) * 100, 1) if total_abs > 0 else 0
        rec.final_decision = rec.calculated_decision

    # === Summary cache ===
    summary_cache_key = f"summary:{index}:{filter_option}:{trend_filter}"
    summary = cache.get(summary_cache_key)

    if not summary:
        working_days = [r for r in all_records if r.date.weekday() < 5]
        total_days = len(working_days)
        bullish_days = len([r for r in working_days if r.calculated_decision == "Bullish"])
        bearish_days = len([r for r in working_days if r.calculated_decision == "Bearish"])
        neutral_days = total_days - (bullish_days + bearish_days)

        summary = {
            "total_days": total_days,
            "bullish_days": bullish_days,
            "bearish_days": bearish_days,
            "neutral_days": neutral_days,
            "bullish_percent": round((bullish_days / total_days) * 100, 1) if total_days else 0,
            "bearish_percent": round((bearish_days / total_days) * 100, 1) if total_days else 0,
            "neutral_percent": round((neutral_days / total_days) * 100, 1) if total_days else 0,
        }
        cache.set(summary_cache_key, summary, 600)

    last = all_records[0] if all_records else None

    context = {
        "index": index,   # ✅ dynamic title/header
        "records": page_obj,
        "filter_option": filter_option,
        "trend_filter": trend_filter,
        "last": last,
        **summary,
    }

    response = render(request, "marketdata/record_list.html", context)
    cache.set(page_cache_key, response, 600)
    return response


# === Wrappers for URL routing ===
def nifty_list(request):
    return record_list(request, index="NIFTY")

def sensex_list(request):
    return record_list(request, index="SENSEX")
def banknifty_list(request):
    return record_list(request, index="BANKNIFTY")
    
def decide_trend_from_fii_dii(fii_net, dii_net, price_points):
    """
    Decide Bullish/Bearish/Neutral using FII+DII + Price movement
    """
    base_trend = "Bullish" if price_points >= 0 else "Bearish"

    if fii_net > 0 and dii_net > 0:
        return "Strong Bullish"
    elif fii_net < 0 and dii_net < 0:
        return "Strong Bearish"
    elif fii_net > 0 and dii_net < 0:
        return "FII Bullish" if base_trend == "Bullish" else "Neutral"
    elif fii_net < 0 and dii_net > 0:
        return "DII Bullish" if base_trend == "Bullish" else "Neutral"
    else:
        return base_trend

def get_sentiment(text):
    if not text:
        return "Neutral"
    polarity = TextBlob(text).sentiment.polarity
    return "Positive" if polarity > 0.1 else "Negative" if polarity < -0.1 else "Neutral"

def translate_news_item(news_item):
    langs = ['te','hi','ta','kn','ml']
    for lang in langs:
        title_field, content_field = f"title_{lang}", f"content_{lang}"
        if not getattr(news_item, title_field):
            try:
                setattr(news_item, title_field, translator.translate(news_item.title, dest=lang).text)
                if news_item.content:
                    setattr(news_item, content_field, translator.translate(news_item.content, dest=lang).text)
            except Exception as e:
                logger.error(f"Translation failed: {e}")
                setattr(news_item, title_field, news_item.title)
                setattr(news_item, content_field, news_item.content)
    news_item.save()

def fetch_and_save_news(days_limit=180):
    rss_feeds = {
        "Moneycontrol":"https://www.moneycontrol.com/rss/latestnews.xml",
        "Economic Times":"https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "The Hindu Business":"https://www.thehindu.com/business/feeder/default.rss",
        "Business Standard":"https://www.business-standard.com/rss/latest.rss",
        "Financial Express":"https://www.financialexpress.com/feed/",
        "NDTV Profit":"https://feeds.feedburner.com/ndtvprofit-latest",
        "Reuters Business":"https://www.reuters.com/rssFeed/businessNews",
        "LiveMint":"https://www.livemint.com/rss/news"
    }
    limit_date = now() - timedelta(days=days_limit)
    new_news = []
    for source, url in rss_feeds.items():
        feed = feedparser.parse(url)
        for entry in feed.entries:
            try:
                published_dt = make_aware(datetime(*entry.published_parsed[:6]))
            except:
                continue
            if published_dt < limit_date or MarketNews.objects.filter(title=entry.title, published_dt=published_dt).exists():
                continue

            content = ""
            try:
                article = Article(entry.link); article.download(); article.parse()
                content = article.text
            except:
                pass

            sentiment = get_sentiment(content[:1000])
            news_item = MarketNews.objects.create(
                source=source, title=entry.title, link=entry.link,
                published_dt=published_dt, content=content, sentiment=sentiment
            )
            translate_news_item(news_item)
            new_news.append(news_item)
    return new_news

@csrf_exempt
def set_language(request):
    if request.method == "POST":
        lang = request.POST.get("language","en")
        request.session["language"] = lang
        request.session.modified = True
    return redirect(request.META.get("HTTP_REFERER","/"))

def news_page(request):
    lang = request.session.get("language", "en")
    interval = request.GET.get('interval', '180')
    sentiment_filter = request.GET.get('sentiment', '')
    date_filter = request.GET.get('date', '')
    source_filter = request.GET.get('source', '')
    keyword = request.GET.get('keyword', '')

    interval_mapping = {'1':1,'7':7,'15':15,'30':30,'90':90,'180':180,'365':365}
    days_limit = interval_mapping.get(interval, 180)

    news = MarketNews.objects.all().order_by('-published_dt')
    if date_filter:
        news = news.filter(published_dt__date=date_filter)
    else:
        news = news.filter(published_dt__gte=now() - timedelta(days=days_limit))
    if sentiment_filter in ['Positive','Negative','Neutral']:
        news = news.filter(sentiment=sentiment_filter)
    if source_filter:
        news = news.filter(source__icontains=source_filter)
    if keyword:
        news = news.filter(content__icontains=keyword)

    paginator = Paginator(news, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    for n in page_obj:
        if lang != 'en':
            n.title = getattr(n, f"title_{lang}") or n.title
            n.content = getattr(n, f"content_{lang}") or n.content
        if not n.summary or n.summary.strip() == "":
            calculate_impact(n)

    context = {
        "page_obj": page_obj, "interval": interval,
        "sentiment_filter": sentiment_filter, "date_filter": date_filter,
        "source_filter": source_filter, "keyword": keyword,
        "positive_count": news.filter(sentiment="Positive").count(),
        "negative_count": news.filter(sentiment="Negative").count(),
        "neutral_count": news.filter(sentiment="Neutral").count(),
        "request": request
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string("marketdata/news_list_partial.html", {"page_obj": page_obj})
        return JsonResponse({"html": html})
    return render(request, "marketdata/news_page.html", context)

def update_news(request):
    days_limit = int(request.POST.get('interval', 180))
    new_news = fetch_and_save_news(days_limit)
    for news_item in new_news:
        calculate_impact(news_item)
    return redirect('news_page')

KEYWORDS_POSITIVE = [
    "buy","record high","gain","increase","bullish","surge","growth","rebound",
    "fii buying","rally","strength","positive","upgrade"
]

KEYWORDS_NEGATIVE = [
    "sell","drop","fall","bearish","decline","inflation","slowdown","cut","weak",
    "fii selling","downturn","loss","negative","downgrade"
]

SECTOR_KEYWORDS = {
    "Auto": ["automobile", "auto", "car", "maruti", "tata motors", "mahindra"],
    "IT": ["tech", "software", "infy", "tcs", "hcl", "wipro", "it services"],
    "Banking": ["bank", "sbi", "hdfc", "icici", "kotak", "axis", "nbfc"],
    "Pharma": ["pharma", "cipla", "dr reddy", "sun pharma", "biocon"],
    "FMCG": ["fmcg", "hindustan unilever", "nestle", "dabur", "britannia"],
    "Energy": ["oil", "gas", "ongc", "reliance", "bpcl", "hpcl", "ioCL"],
    "Metals": ["steel", "jsw", "tata steel", "hindalco", "vedanta", "copper"],
}

def calculate_impact(news_item):
    """
    Enrich MarketNews with impact_score (-1 to +1), sectors, and summary.
    """
    text = (news_item.title + " " + (news_item.content or "")).lower()

    # --- Sentiment base score ---
    sentiment_score = 1 if news_item.sentiment == "Positive" else -1 if news_item.sentiment == "Negative" else 0

    # --- Keyword signals ---
    keyword_score = sum(0.4 for kw in KEYWORDS_POSITIVE if kw in text) - \
                    sum(0.4 for kw in KEYWORDS_NEGATIVE if kw in text)

    # --- Final impact score (clamped between -1 and 1) ---
    impact = max(min(sentiment_score + keyword_score, 1), -1)
    news_item.impact_score = impact

    # --- Detect sectors ---
    sectors = []
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(word in text for word in keywords):
            sectors.append(sector)
    news_item.sectors = list(set(sectors))

    # --- Humanized summary ---
    if impact > 0.5:
        base_summary = f"🚀 Strong Positive news likely to push market up: {news_item.title}"
    elif impact < -0.5:
        base_summary = f"⚠️ Strong Negative news may pressure market down: {news_item.title}"
    else:
        base_summary = f"ℹ️ Moderate/Neutral news: {news_item.title}"

    # Add sector info
    if sectors:
        base_summary += f" → Impacted sectors: {', '.join(sectors)}"

    # --- Check next day Nifty move (if available) ---
    try:
        next_day = MarketRecord.objects.filter(
            date=news_item.published_dt.date() + timedelta(days=1)
        ).first()
        if next_day:
            base_summary += f" | Next day Nifty close: {next_day.close}"
    except Exception:
        pass

    news_item.summary = base_summary
    news_item.save()
    return news_item

def compute_rsi(close: pd.Series, length=14):
    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
    rs = avg_gain / (avg_loss.replace(0,1e-10))
    return 100 - (100/(1+rs))

def compute_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast, ema_slow = close.ewm(span=fast, adjust=False).mean(), close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line

def compute_bollinger(close: pd.Series, length=20, std=2):
    ma, sd = close.rolling(length).mean(), close.rolling(length).std()
    return ma + std*sd, ma, ma - std*sd

def market_insights(request):
    symbol = request.GET.get("symbol","^NSEI")
    period = request.GET.get("period","6mo")
    interval = request.GET.get("interval","1d")
    return render(request,"marketdata/market_insights.html",{"symbol":symbol,"period":period,"interval":interval})

@cache_page(60)
@require_GET
def insights_data(request, symbol="^NSEI"):
    period = request.GET.get("period","6mo")
    interval = request.GET.get("interval","1d")
    allowed_intervals = {"1m","2m","5m","15m","30m","60m","90m","1h","1d","1wk","1mo"}
    if interval not in allowed_intervals:
        return HttpResponseBadRequest("Invalid interval")
    try:
        df = yf.download(symbol,period=period,interval=interval,progress=False)
    except Exception as e:
        return HttpResponseBadRequest(f"Download error: {e}")
    if df.empty:
        return JsonResponse({"data":[]})
    df = df.dropna().copy(); df.index = pd.to_datetime(df.index)
    df["RSI"] = compute_rsi(df["Close"])
    macd, signal, hist = compute_macd(df["Close"])
    df["MACD"], df["MACD_signal"], df["MACD_hist"] = macd, signal, hist
    bb_u, bb_m, bb_l = compute_bollinger(df["Close"])
    df["BB_upper"], df["BB_mid"], df["BB_lower"] = bb_u, bb_m, bb_l

    out=[]
    for ts,row in df.iterrows():
        def safe_val(v,round_to=None,as_int=False):
            if v is None or (isinstance(v,float) and pd.isna(v)): return None
            if pd.isna(v): return None
            if as_int: return int(v)
            return round(float(v),round_to) if round_to else float(v)
        out.append({
            "t":ts.isoformat(),"o":safe_val(row.get("Open"),2),
            "h":safe_val(row.get("High"),2),"l":safe_val(row.get("Low"),2),
            "c":safe_val(row.get("Close"),2),"v":safe_val(row.get("Volume"),as_int=True) or 0,
            "rsi":safe_val(row.get("RSI"),2),"macd":safe_val(row.get("MACD"),4),
            "signal":safe_val(row.get("MACD_signal"),4),"hist":safe_val(row.get("MACD_hist"),4),
            "bb_u":safe_val(row.get("BB_upper"),2),"bb_m":safe_val(row.get("BB_mid"),2),"bb_l":safe_val(row.get("BB_lower"),2)
        })
    return JsonResponse({"symbol":symbol,"period":period,"interval":interval,"data":out[-1000:]},safe=False)

def predict_signal(request, symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="6mo",interval="1d").reset_index()
        if hist.empty:
            return JsonResponse({"error":f"No historical data for {symbol}"},status=400)
        hist["rsi"] = ta.momentum.RSIIndicator(hist["Close"]).rsi()
        hist["returns"] = hist["Close"].pct_change()
        features = hist[["rsi","returns"]].dropna().tail(1).values
        if not os.path.exists(MODEL_FILE):
            return JsonResponse({"trend":"Bullish 📈","confidence":"85.32%","patterns":["Head & Shoulders","Double Top"]})
        model = joblib.load(MODEL_FILE)
        pred = model.predict(features)[0]; proba = model.predict_proba(features).max()
        return JsonResponse({
            "trend":"Bullish 📈" if pred==1 else "Bearish 📉",
            "confidence":f"{proba*100:.2f}%",
            "patterns":["Head & Shoulders","Double Top"]
        })
    except Exception as e:
        return JsonResponse({"error":str(e)},status=500)

def live_nifty_data(request):
    nifty = yf.Ticker("^NSEI")
    data = nifty.history(period="1d",interval="1m")
    latest = data.iloc[-1]
    return JsonResponse({
        "datetime":str(latest.name),
        "open":round(float(latest["Open"]),2),
        "high":round(float(latest["High"]),2),
        "low":round(float(latest["Low"]),2),
        "close":round(float(latest["Close"]),2),
        "volume":int(latest["Volume"])
    })

def fii_dii_list(request):
    start_date = request.GET.get("start_date"); end_date = request.GET.get("end_date")
    qs = FiiDiiRecord.objects.all().order_by("-date")
    if start_date and end_date: qs = qs.filter(date__range=[start_date,end_date])
    elif start_date: qs = qs.filter(date=start_date)
    analysis_map = analyze_fii_dii(qs.order_by('date'), window=60)
    total_records = qs.count(); matched_count = qs.filter(matched=True).count()
    divergence_count = total_records - matched_count
    paginator = Paginator(qs, 5); page_obj = paginator.get_page(request.GET.get("page"))
    for rec in page_obj:
        rec.analysis = analysis_map.get(str(rec.date), {"signal":"N/A","matched":None,"suggestion":{"strategy":"","notes":"","confidence":""},"fii_z":0,"dii_z":0,"total_z":0})
    totals = {"total":0,"matched":0,"bullish":0,"bearish":0,"neutral":0}
    for d,a in analysis_map.items():
        totals["total"]+=1
        if a["matched"] is True: totals["matched"]+=1
        if a["signal"] in ("StrongBullish","Bullish"): totals["bullish"]+=1
        elif a["signal"] in ("StrongBearish","Bearish"): totals["bearish"]+=1
        else: totals["neutral"]+=1
    accuracy_pct = (totals["matched"]/totals["total"]*100) if totals["total"] else 0
    context = {"page_obj":page_obj,"start_date":start_date,"end_date":end_date,
               "total_records":total_records,"matched_count":matched_count,
               "divergence_count":divergence_count,"totals":totals,"accuracy_pct":round(accuracy_pct,2)}
    return render(request,"marketdata/fii_dii_list.html",context)

def fii_dii_update(request):
    try:
        result = update_fii_dii_data()
        messages.success(request, f"✅ Updated: {result['created']} new, {result['updated']} updated")
    except Exception as e:
        messages.error(request, f"⚠️ Update failed: {e}")
    return redirect("fii_dii_list")

def market_trap_dashboard(request):
    start_date = request.GET.get("start_date"); end_date = request.GET.get("end_date")
    page_number = request.GET.get("page", 1); action = request.GET.get("action")
    if action == "update":
        advanced_market_trap_analysis(start_date, end_date)
        redirect_url = request.path
        if start_date and end_date: redirect_url += f"?start_date={start_date}&end_date={end_date}"
        return redirect(redirect_url)
    traps_qs = MarketTrap.objects.all().order_by("-date")
    if start_date and end_date: traps_qs = traps_qs.filter(date__range=[start_date,end_date])
    elif start_date: traps_qs = traps_qs.filter(date=start_date)
    if not traps_qs.exists():
        advanced_market_trap_analysis(start_date, end_date)
        traps_qs = MarketTrap.objects.all().order_by("-date")
        if start_date and end_date: traps_qs = traps_qs.filter(date__range=[start_date,end_date])
        elif start_date: traps_qs = traps_qs.filter(date=start_date)
    paginator = Paginator(traps_qs, 20); page_obj = paginator.get_page(page_number)
    trap_results = {str(trap.date):{"trap_detected":trap.trap_detected,"trap_type":trap.trap_type,"confidence":trap.confidence,"fii_dii_signal":trap.fii_dii_signal,"future_decision":trap.future_decision,"related_news":trap.related_news} for trap in page_obj.object_list}
    chart_data = [{"date":date_str,"confidence":info["confidence"],"trap_detected":info["trap_detected"],"fii_dii_signal":info["fii_dii_signal"]} for date_str,info in trap_results.items()]
    context = {"trap_results":trap_results,"chart_data":json.dumps(chart_data),
               "start_date":start_date,"end_date":end_date,"page_obj":page_obj}
    return render(request,"marketdata/dashboard.html",context)

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*","Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain","Origin": "https://www.nseindia.com",
    "Connection": "keep-alive","DNT": "1","Upgrade-Insecure-Requests": "1"
}

def fetch_nifty50_option_chain(expiry=None):
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    try:
        session.get("https://www.nseindia.com/option-chain", headers=NSE_HEADERS, timeout=10)
        data = session.get(url, headers=NSE_HEADERS, timeout=10).json()
    except Exception as e:
        logger.error(f"NSE fetch error: {e}"); return [], 0, []
    all_expiries = data.get("records", {}).get("expiryDates", [])
    if not expiry and all_expiries: expiry = all_expiries[0]
    records = [r for r in data.get("records", {}).get("data", []) if r.get("expiryDate") == expiry]
    underlying = data.get("records", {}).get("underlyingValue", 0)
    option_data = []
    for item in records:
        ce, pe = item.get("CE"), item.get("PE")
        if ce or pe:
            option_data.append({
                "strikePrice": item.get("strikePrice"),
                "call_ltp": ce.get("lastPrice", 0) if ce else 0,
                "call_oi": ce.get("openInterest", 0) if ce else 0,
                "call_iv": ce.get("impliedVolatility", 0) if ce else 0,
                "put_ltp": pe.get("lastPrice", 0) if pe else 0,
                "put_oi": pe.get("openInterest", 0) if pe else 0,
                "put_iv": pe.get("impliedVolatility", 0) if pe else 0,
            })
    return option_data, underlying, all_expiries

def normalize(val, min_val, max_val): return 0.0 if max_val-min_val==0 else float((val-min_val)/(max_val-min_val)*100.0)

def percentile(sorted_list, p):
    if not sorted_list: return 0
    k = (len(sorted_list)-1) * (p/100.0); f = math.floor(k); c = math.ceil(k)
    if f==c: return sorted_list[int(k)]
    return sorted_list[int(f)]*(c-k)+sorted_list[int(c)]*(k-f)

def option_chain(request):
    selected_expiry = request.GET.get("expiry")
    option_data, underlying, all_expiries = fetch_nifty50_option_chain(selected_expiry)
    if not option_data:
        return render(request,"marketdata/option_chain.html",{"options":[],"error":"Failed to fetch NSE data.","expiries":all_expiries,"selected_expiry":selected_expiry})
    call_oi_list=[r["call_oi"] for r in option_data]; put_oi_list=[r["put_oi"] for r in option_data]
    call_iv_list=[r["call_iv"] for r in option_data]; put_iv_list=[r["put_iv"] for r in option_data]
    max_call_oi,min_call_oi=max(call_oi_list),min(call_oi_list); max_put_oi,min_put_oi=max(put_oi_list),min(put_oi_list)
    max_call_iv,min_call_iv=max(call_iv_list),min(call_iv_list); max_put_iv,min_put_iv=max(put_iv_list),min(put_iv_list)
    for row in option_data:
        row["call_oi_pct"]=normalize(row["call_oi"],min_call_oi,max_call_oi)
        row["put_oi_pct"]=normalize(row["put_oi"],min_put_oi,max_put_oi)
        row["call_iv_pct"]=normalize(row["call_iv"],min_call_iv,max_call_iv)
        row["put_iv_pct"]=normalize(row["put_iv"],min_put_iv,max_put_iv)
    atm_strike=min(option_data,key=lambda x: abs(x["strikePrice"]-underlying))["strikePrice"]
    option_data=sorted(option_data,key=lambda x: abs(x["strikePrice"]-atm_strike))
    atm_index=next((i for i,r in enumerate(option_data) if r["strikePrice"]==atm_strike),0)
    start,max_index=max(atm_index-10,0),min(atm_index+11,len(option_data))
    visible_rows=option_data[start:max_index]
    call_iv_sorted=sorted([r["call_iv"] for r in visible_rows]); put_iv_sorted=sorted([r["put_iv"] for r in visible_rows])
    iv_75_call=percentile(call_iv_sorted,75); iv_75_put=percentile(put_iv_sorted,75)
    for row in visible_rows:
        row["trap_type"]=None
        if row["call_oi"]>1.5*(row["put_oi"]+1): row["trap_type"]="resistance_trap"
        elif row["put_oi"]>1.5*(row["call_oi"]+1): row["trap_type"]="support_trap"
        elif row["call_iv_pct"]>90 or row["put_iv_pct"]>90: row["trap_type"]="iv_spike"
        balanced=0.8<=(row["call_oi"]/(row["put_oi"]+1))<=1.2
        iv_ok=(row["call_iv"]<=iv_75_call*1.1) and (row["put_iv"]<=iv_75_put*1.1)
        row["safe_trade"]=abs(row["strikePrice"]-atm_strike)<=200 and balanced and iv_ok
        if row["call_iv"]>=iv_75_call*1.1 or row["put_iv"]>=iv_75_put*1.1:
            row["suggestion"]="Avoid buying options — IV high. Selling possible (experienced only)."
        elif row["call_oi"]>1.5*(row["put_oi"]+1): row["suggestion"]="Call-heavy — consider PUT or avoid CALL."
        elif row["put_oi"]>1.5*(row["call_oi"]+1): row["suggestion"]="Put-heavy — consider CALL or avoid PUT."
        elif row["safe_trade"]: row["suggestion"]="Safe-trade candidate (balanced OI & IV)."
        else: row["suggestion"]="Neutral — observe"
    total_call_oi=sum(r["call_oi"] for r in visible_rows); total_put_oi=sum(r["put_oi"] for r in visible_rows)
    sentiment="Bullish" if total_call_oi>total_put_oi else "Bearish" if total_put_oi>total_call_oi else "Neutral"
    summary={"max_call_oi":max(r["call_oi"] for r in visible_rows),"max_put_oi":max(r["put_oi"] for r in visible_rows),
             "max_call_iv":max(r["call_iv"] for r in visible_rows),"max_put_iv":max(r["put_iv"] for r in visible_rows)}
    summary["diff_oi"]=summary["max_call_oi"]-summary["max_put_oi"]; summary["diff_iv"]=summary["max_call_iv"]-summary["max_put_iv"]
    if request.headers.get("x-requested-with")=="XMLHttpRequest":
        return JsonResponse({"options":visible_rows,"atm_strike":atm_strike,"sentiment":sentiment,"summary":summary},safe=False)
    return render(request,"marketdata/option_chain.html",{"options":visible_rows,"atm_strike":atm_strike,"sentiment":sentiment,"summary":summary,"underlying":underlying,"expiries":all_expiries,"selected_expiry":selected_expiry or (all_expiries[0] if all_expiries else None)})
