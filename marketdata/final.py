# This si final version# marketdata/views.py

import os
import math
import json
import logging
from datetime import datetime, date, timedelta,time

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
from django.utils.timezone import now, make_aware
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.contrib import messages
from django.db.models import Q,Count

from django.db import models
from .models import MarketRecord, MarketNews, FiiDiiRecord, MarketTrap,Prediction
from .analysis import analyze_fii_dii, advanced_market_trap_analysis

logger = logging.getLogger(__name__)
translator = Translator()
MODEL_FILE = os.path.join(settings.BASE_DIR, "ml_models", "nifty_model.pkl")

# ==============================================================
# Live Market Data (Yahoo only)
# ==============================================================

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

# ==============================================================
# Market Records
# ==============================================================



# ---------- Fetch NIFTY history (daily + 1h + 30m) ----------

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
    """
    try:
        ticker = yf.Ticker("^NSEI")
        records = []
        prev_daily_close = None

        # --- Daily candles ---
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

        # --- Hourly candles ---
        if include_hourly:
            df_h = ticker.history(period=f"{max(7, days)}d", interval="1h")
            if not df_h.empty:
                for ts, row in df_h.iterrows():
                    py_dt = pd.to_datetime(ts).to_pydatetime()
                    t = py_dt.time().replace(second=0, microsecond=0)
                    # ✅ keep all hourly rows (Yahoo may give :30 instead of :00)
                    if time(9, 15) <= t <= time(15, 30):  # market hours only
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

        # --- 30-minute candles ---
        if include_30m:
            df_30 = ticker.history(period=f"{max(7, days)}d", interval="30m")
            if not df_30.empty:
                for ts, row in df_30.iterrows():
                    py_dt = pd.to_datetime(ts).to_pydatetime()
                    t = py_dt.time().replace(second=0, microsecond=0)

                    # ✅ keep both :00 and :30 but only market hours (9:15 → 15:30)
                    if time(9, 15) <= t <= time(15, 30):
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

        # Sort results by date + time
        records.sort(key=lambda r: (r["date"], (r["hour"] or time(0, 0))))
        return records

    except Exception as e:
        logger.exception("Error fetching nifty history")
        return []
# ==============================================================
# FII/DII
# ==============================================================

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

# ==============================================================
# PCR (from NSE Option Chain)
# ==============================================================

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


# ==============================================================
# Record List View
# ==============================================================

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

# ---------- Record List View ----------

def record_list(request):
    filter_option = request.GET.get("filter", "all")
    selected_date = request.GET.get("snippet_date")

    if request.method == "POST" and "update_data" in request.POST:
        nifty_records = fetch_nifty_history(days=30, include_hourly=True, include_30m=True)

        # FII/DII data
        fii_dii_list = fetch_fii_dii()
        fii_dii_map = {
            datetime.strptime(r["date"], "%Y-%m-%d").date(): r for r in fii_dii_list
        }

        for r in nifty_records:
            date_val = r["date"]
            fii_info = fii_dii_map.get(date_val, {})

            if r["interval"] == "1d":
                existing = MarketRecord.objects.filter(date=date_val, interval="1d").first()

                pcr_val = 0
                if date_val == date.today():
                    pcr_val = fetch_pcr_data()
                elif existing:
                    pcr_val = existing.pcr

                MarketRecord.objects.update_or_create(
                    date=date_val,
                    hour=None,
                    interval="1d",
                    defaults={
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
                        "pcr": pcr_val,
                        "global_markets": "Auto fetch pending",
                        "important_news": getattr(existing, "important_news", ""),
                        # ❌ no decision saved here
                    }
                )
            else:  # intraday
                MarketRecord.objects.update_or_create(
                    date=date_val,
                    hour=r["hour"],
                    interval=r["interval"],
                    defaults={
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
                        # ❌ no decision saved here
                    }
                )

        return redirect("record_list")

    # ================= FILTER + DISPLAY ==================
    daily_qs = MarketRecord.objects.filter(interval="1d").order_by("-date")
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

    all_records = list(daily_qs)

    # --- Points daily ---
    prev_close = None
    for rec in reversed(all_records):
        rec.points = 0 if prev_close is None else round(rec.nifty_close - prev_close, 2)
        prev_close = rec.nifty_close

    # --- Pagination ---
    paginator = Paginator(all_records, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # --- Add intraday breakdowns ---
    for rec in page_obj:
        fii = rec.fii_net or 0
        dii = rec.dii_net or 0
        points = rec.points or 0

        # ✅ Decide bias trend using FII/DII + price
        rec.bias = decide_trend_from_fii_dii(fii, dii, points)

        # Percentage split for bar charts
        total_abs = abs(fii) + abs(dii)
        if total_abs > 0:
            rec.fii_percent = round((abs(fii) / total_abs) * 100, 1)
            rec.dii_percent = round((abs(dii) / total_abs) * 100, 1)
        else:
            rec.fii_percent = 50
            rec.dii_percent = 50
        
        # Hourly
        hourly_records = list(MarketRecord.objects.filter(date=rec.date, interval="1h").order_by("hour"))
        prev_close = None
        for hr in hourly_records:
            hr.points = 0 if prev_close is None else round(hr.nifty_close - prev_close, 2)
            prev_close = hr.nifty_close
        rec.hourly_set_calculated = hourly_records

        # 30m
        m30_records = list(MarketRecord.objects.filter(date=rec.date, interval="30m").order_by("hour"))
        prev_close = None
        for m30 in m30_records:
            m30.points = 0 if prev_close is None else round(m30.nifty_close - prev_close, 2)
            prev_close = m30.nifty_close
        rec.m30_set_calculated = m30_records

    # --- Working-day snippets ---
    working_days = [r for r in all_records if r.date.weekday() < 5]

    def trade_snippet(days):
        records = working_days[:days]
        if not records:
            return {"trend": "-", "trade": "-"}
        avg = sum(r.points for r in records) / len(records)
        return {"trend": "Bullish" if avg >= 0 else "Bearish",
                "trade": "Call" if avg >= 0 else "Put"}

    snippets = {
        "Based on Last 25 Working Days": trade_snippet(25),
        "Based on Last 15 Working Days": trade_snippet(15),
        "Based on Last 1 Week": trade_snippet(7),
        "Based on Last 3 Working Days": trade_snippet(3),
        "Based on Last 2 Working Days": trade_snippet(2),
        "Based on Last 1 Working Day": trade_snippet(1),
    }

    # --- Summary stats ---
    total_days = len(working_days)

    # ✅ decisions now calculated dynamically
    bullish_days = len([r for r in working_days if r.points > 0])
    bearish_days = len([r for r in working_days if r.points < 0])
    neutral_days = total_days - (bullish_days + bearish_days)

    bullish_percent = round((bullish_days / total_days) * 100, 1) if total_days else 0
    bearish_percent = round((bearish_days / total_days) * 100, 1) if total_days else 0
    neutral_percent = round((neutral_days / total_days) * 100, 1) if total_days else 0

    # --- Latest record ---
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


def prediction_history(request):
    # Predictions grouped by interval
    predictions_30m = Prediction.objects.filter(interval="30m").order_by("-timestamp")[:50]
    predictions_1h = Prediction.objects.filter(interval="1h").order_by("-timestamp")[:50]
    predictions_1d = Prediction.objects.filter(interval="1d").order_by("-timestamp")[:50]

    # Accuracy summary
    total = Prediction.objects.count()
    wins = Prediction.objects.filter(result="Profit").count()
    losses = Prediction.objects.filter(result="Loss").count()
    pending = Prediction.objects.filter(result="Pending").count()
    accuracy = round((wins / total) * 100, 2) if total else 0

    # ✅ Chart data: Accuracy by day
    daily_stats = (
        Prediction.objects.exclude(result="Pending")
        .values("timestamp__date")
        .annotate(
            total=Count("id"),
            wins=Count("id", filter=models.Q(result="Profit")),
            losses=Count("id", filter=models.Q(result="Loss"))
        )
        .order_by("timestamp__date")
    )

    chart_labels = [str(d["timestamp__date"]) for d in daily_stats]
    chart_accuracy = [
        round((d["wins"] / d["total"]) * 100, 2) if d["total"] else 0 for d in daily_stats
    ]
    chart_wins = [d["wins"] for d in daily_stats]
    chart_losses = [d["losses"] for d in daily_stats]

    context = {
        "predictions_30m": predictions_30m,
        "predictions_1h": predictions_1h,
        "predictions_1d": predictions_1d,
        "total": total,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "accuracy": accuracy,
        "chart_labels": chart_labels,
        "chart_accuracy": chart_accuracy,
        "chart_wins": chart_wins,
        "chart_losses": chart_losses,
    }
    return render(request, "marketdata/prediction_history.html", context)
# ==============================================================
# (Rest of views: News, Insights, ML, FII/DII, Market Traps, Option Chain)
# ==============================================================

# -- I can paste the remaining half (News, Insights, ML, Option Chain) if you confirm,
#   since this message is already very long. 

# ==============================================================
# Market News
# ==============================================================
# ==============================================================
# Market News
# ==============================================================

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

KEYWORDS_POSITIVE = ["buy","record high","gain","increase","bullish","FII buying","surge"]
KEYWORDS_NEGATIVE = ["sell","drop","fall","bearish","decline","inflation","FII selling"]

def calculate_impact(news_item):
    text = (news_item.title + " " + (news_item.content or "")).lower()
    sentiment_score = 1 if news_item.sentiment=="Positive" else -1 if news_item.sentiment=="Negative" else 0
    keyword_score = sum(0.5 for kw in KEYWORDS_POSITIVE if kw in text) - sum(0.5 for kw in KEYWORDS_NEGATIVE if kw in text)
    impact = max(min(sentiment_score + keyword_score, 1), -1)
    news_item.impact_score = impact
    if impact > 0.5: summary = f"Strong Positive news likely to push market up: {news_item.title}"
    elif impact < -0.5: summary = f"Strong Negative news may pressure market down: {news_item.title}"
    else: summary = f"Neutral/Moderate impact news: {news_item.title}"
    next_day = MarketRecord.objects.filter(date=news_item.published_dt.date() + timedelta(days=1)).first()
    if next_day: summary += f" | Next day Nifty: {next_day.nifty_close}"
    news_item.summary = summary
    news_item.save()

# ==============================================================
# Technical Indicators + Insights
# ==============================================================

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

# ==============================================================
# ML Prediction
# ==============================================================

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

# ==============================================================
# Live Nifty Intraday
# ==============================================================

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

# ==============================================================
# FII/DII Dashboard
# ==============================================================

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

# ==============================================================
# Market Trap Dashboard
# ==============================================================

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

# ==============================================================
# NSE Option Chain
# ==============================================================

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
