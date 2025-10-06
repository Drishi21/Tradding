from django import forms
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Avg, Sum
from datetime import date
from functools import lru_cache
import pandas as pd
import holidays
import json

from marketdata.models import MarketRecord
from .models import OptionReversal


# ==========================================================
# 1️⃣ Filter Form
# ==========================================================
class ReversalFilterForm(forms.Form):
    index = forms.ChoiceField(
        choices=[("", "All")] + OptionReversal.INDEX_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    interval = forms.ChoiceField(
        choices=[("", "All"), ("1d", "Daily"), ("1h", "Hourly"), ("30m", "30-Minute")],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    momentum_bias = forms.ChoiceField(
        choices=[
            ("", "All"),
            ("BUY_CE", "Call Bias (Bullish)"),
            ("BUY_PE", "Put Bias (Bearish)"),
            ("NEUTRAL", "Neutral"),
        ],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
# ==========================================================
# 2️⃣ Utility Helpers
# ==========================================================
# ==========================================================

@lru_cache(maxsize=1)
def get_india_holidays():
    this_year = date.today().year
    return holidays.India(years=[this_year - 1, this_year, this_year + 1])



def calculate_pivot_levels_with_hint(high, low, close):
    P = (high + low + close) / 3
    R1, S1 = (2 * P) - low, (2 * P) - high
    R2, S2 = P + (high - low), P - (high - low)
    R3, S3 = high + 2 * (P - low), low - 2 * (high - P)

    if close > R3:
        sentiment, hint = "Strong Bullish", "🚀 Above R3 — strong breakout."
    elif R2 < close <= R3:
        sentiment, hint = "Bullish", "📈 Between R2–R3 — strong upward momentum."
    elif R1 < close <= R2:
        sentiment, hint = "Moderate Bullish", "🟢 Above Pivot — positive bias."
    elif S1 < close <= P:
        sentiment, hint = "Neutral", "⚪ Near Pivot — sideways consolidation."
    elif S2 < close <= S1:
        sentiment, hint = "Reversal Chance", "🟠 Testing S1–S2 — possible rebound."
    elif S3 < close <= S2:
        sentiment, hint = "Bearish", "🔻 Between S2–S3 — bearish continuation."
    else:
        sentiment, hint = "Strong Bearish", "⚫ Below S3 — heavy selling pressure."

    return {
        "P": round(P, 2), "R1": round(R1, 2), "R2": round(R2, 2), "R3": round(R3, 2),
        "S1": round(S1, 2), "S2": round(S2, 2), "S3": round(S3, 2),
        "sentiment": sentiment, "hint": hint
    }

def generate_confluence_signal(reversal_trend, pivot_sentiment):
    if not reversal_trend or not pivot_sentiment:
        return {"label": "⚪ No Data", "color": "gray",
                "desc": "Insufficient data for confluence.",
                "plan": "No trade — waiting for clear market bias."}

    r, p = reversal_trend.lower(), pivot_sentiment.lower()

    if "bullish" in r and "bullish" in p:
        return {"label": "🟢 Bullish Confluence", "color": "green",
                "desc": "Momentum and pivot align bullishly.",
                "plan": "💹 Suggested: BUY_CE or go LONG."}
    if "bearish" in r and "bearish" in p:
        return {"label": "🔴 Bearish Confluence", "color": "red",
                "desc": "Momentum and pivot confirm bearishness.",
                "plan": "📉 Suggested: BUY_PE or SHORT futures."}
    if ("bullish" in r and "bearish" in p) or ("bearish" in r and "bullish" in p):
        return {"label": "⚫ Conflict", "color": "gray",
                "desc": "Momentum vs pivot conflict.",
                "plan": "⛔ Avoid entry."}
    return {"label": "⚪ Neutral", "color": "gray",
            "desc": "No strong directional bias.",
            "plan": "🕒 Wait for breakout."}


# ==========================================================
# 3️⃣ Dashboard View
# ==========================================================
def reversal_list(request):
    form = ReversalFilterForm(request.GET or None)
    qs = OptionReversal.objects.all()

    if form.is_valid():
        data = form.cleaned_data
        if data.get("index"):
            qs = qs.filter(index__iexact=data["index"])
        if data.get("interval"):
            qs = qs.filter(interval=data["interval"])
        if data.get("momentum_bias"):
            qs = qs.filter(momentum_bias=data["momentum_bias"])
        if data.get("date_from"):
            qs = qs.filter(reversal_date__gte=data["date_from"])
        if data.get("date_to"):
            qs = qs.filter(reversal_date__lte=data["date_to"])
    else:
        data = {}

    qs = qs.order_by("-reversal_date")
    index = data.get("index") or "NIFTY"

    # === Pivot Levels ===
    pivot_daily = pivot_weekly = pivot_hourly = None
    last_rec = MarketRecord.objects.filter(index=index, interval="1d").order_by("-date").first()
    if last_rec:
        pivot_daily = calculate_pivot_levels_with_hint(float(last_rec.high), float(last_rec.low), float(last_rec.close))

        # Weekly (last 5 daily candles)
        recent5 = MarketRecord.objects.filter(index=index, interval="1d").order_by("-date")[:5]
        if recent5.exists():
            highs = [float(r.high) for r in recent5]
            lows = [float(r.low) for r in recent5]
            closes = [float(r.close) for r in recent5]
            pivot_weekly = calculate_pivot_levels_with_hint(max(highs), min(lows), sum(closes) / len(closes))

        # Hourly (for today)
        today_data = MarketRecord.objects.filter(index=index, interval="1h").order_by("-date")[:8]
        if today_data.exists():
            highs = [float(r.high) for r in today_data]
            lows = [float(r.low) for r in today_data]
            closes = [float(r.close) for r in today_data]
            pivot_hourly = calculate_pivot_levels_with_hint(max(highs), min(lows), sum(closes) / len(closes))

    # === Confidence Heatmap ===
    conf_dates, conf_values, conf_colors = [], [], []
    for r in OptionReversal.objects.filter(index=index).order_by("reversal_date"):
        conf_dates.append(r.reversal_date.strftime("%d-%b"))
        conf_values.append(3 if r.to_trend == "Bullish" else -3)
        conf_colors.append("rgba(34,197,94,0.9)" if r.to_trend == "Bullish" else "rgba(239,68,68,0.9)")

    # === Confluence ===
    pivot_sentiment = pivot_daily["sentiment"] if pivot_daily else None
    latest_reversal = qs.first().to_trend if qs.exists() else None
    confluence_signal = generate_confluence_signal(latest_reversal, pivot_sentiment)

    # === Summary ===
    summary = {
        "total": qs.count(),
        "bullish": qs.filter(to_trend="Bullish").count(),
        "bearish": qs.filter(to_trend="Bearish").count(),
        "avg_days": round(qs.aggregate(avg=Avg("new_streak_days"))["avg"] or 0, 2),
        "total_change": round(float(qs.aggregate(sum=Sum("new_change"))["sum"] or 0), 2),
    }

    # === JSON Safe ===
    def j(obj):
        return json.dumps(obj, default=float) if obj else "null"
    conf_dates, conf_values, conf_colors, conf_labels = [], [], [], []
    for r in OptionReversal.objects.filter(index=index).order_by("reversal_date"):
        conf_dates.append(r.reversal_date.strftime("%d-%b"))
        conf_values.append(3 if r.to_trend == "Bullish" else -3)
        conf_colors.append("rgba(34,197,94,0.9)" if r.to_trend == "Bullish" else "rgba(239,68,68,0.9)")
        conf_labels.append(f"{r.from_trend} → {r.to_trend}")

    
    context = {
        "conf_dates": json.dumps(conf_dates),
        "conf_values": json.dumps(conf_values),
        "conf_colors": json.dumps(conf_colors),
        "conf_labels": json.dumps(conf_labels),
        "form": form,
        "reversals": qs,
        "index": index,
        "pivot_daily": j(pivot_daily),
        "pivot_weekly": j(pivot_weekly),
        "pivot_hourly": j(pivot_hourly),
        "confluence_signal": confluence_signal,
        "summary": summary,
        "conf_dates": json.dumps(conf_dates),
        "conf_values": json.dumps(conf_values),
        "conf_colors": json.dumps(conf_colors),
    }
    return render(request, "option_reversal/reversal_list.html", context)


def safe_floatify(obj):
    """Convert Decimal/NaN types to float-safe dicts."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            try:
                result[k] = float(v)
            except Exception:
                result[k] = v
        return result
    return obj

# ==========================================================
# 4️⃣ Update Trigger
# ==========================================================
def update_reversals(request):
    if request.method == "POST":
        total_new = 0
        for idx in ["NIFTY", "SENSEX", "BANKNIFTY"]:
            results = detect_option_reversals(index=idx, interval="1d")
            total_new += len(results)
        messages.success(request, f"✅ Updated successfully — {total_new} new reversals added.")
    return redirect("option_reversal_list")
# ==========================================================
# 3️⃣ Detect Option Reversals
# ==========================================================
def detect_option_reversals(index, interval="1d"):
    """Detect trend reversals from MarketRecord data."""
    qs = MarketRecord.objects.filter(index=index, interval=interval).order_by("date", "hour")
    if not qs.exists():
        print(f"⚠️ No MarketRecord found for {index}")
        return []

    india_holidays = get_india_holidays()
    df = pd.DataFrame([{"date": r.date, "hour": r.hour, "close": float(r.close)} for r in qs])
    df["weekday"] = df["date"].apply(lambda d: d.weekday())
    df = df[(df["weekday"] < 5) & (~df["date"].isin(india_holidays.keys()))]
    df = df.drop_duplicates(subset=["date"]).sort_values("date")

    df["change"] = df["close"].diff()
    df["direction"] = df["change"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    df["streak_id"] = (df["direction"] != df["direction"].shift()).cumsum()

    streaks = df.groupby("streak_id").agg(
        start_date=("date", "first"),
        end_date=("date", "last"),
        direction=("direction", "first"),
        bars=("date", "count"),
        total_change=("change", "sum"),
    ).reset_index(drop=True)

    reversals = []
    for i in range(1, len(streaks)):
        prev_dir, curr_dir = streaks.loc[i - 1, "direction"], streaks.loc[i, "direction"]
        if prev_dir != curr_dir and curr_dir != 0:
            reversal_date = streaks.loc[i, "start_date"]
            if reversal_date.weekday() >= 5 or reversal_date in india_holidays:
                continue
            if OptionReversal.objects.filter(index=index, interval=interval, reversal_date=reversal_date).exists():
                continue

            to_trend = "Bullish" if curr_dir == 1 else "Bearish"
            signal = "BUY_CE" if to_trend == "Bullish" else "BUY_PE"

            OptionReversal.objects.create(
                index=index,
                interval=interval,
                reversal_date=reversal_date,
                from_trend="Bullish" if prev_dir == 1 else "Bearish",
                to_trend=to_trend,
                prev_streak_days=int(streaks.loc[i - 1, "bars"]),
                new_streak_days=int(streaks.loc[i, "bars"]),
                prev_change=round(float(streaks.loc[i - 1, "total_change"]), 2),
                new_change=round(float(streaks.loc[i, "total_change"]), 2),
                momentum_bias=signal,
                remarks=f"Trend reversal detected — Option Bias: {signal}",
            )
            reversals.append(reversal_date)
    print(f"✅ {index}: {len(reversals)} reversals detected.")
    return reversals

