# marketdata/analysis.py
import math
import pandas as pd
import numpy as np
from .models import FiiDiiRecord, MarketRecord

STRONG_Z = 1.0
WEAK_Z = 0.5
ROLL_WINDOW = 60  # use 60 trading days by default

def nearest_strike(price, step=50):
    """Round to nearest strike (50/100 step typical for NIFTY)."""
    return int(round(price / step) * step)

def label_from_z(z):
    if z >= STRONG_Z:
        return "StrongBullish"
    if z >= WEAK_Z:
        return "Bullish"
    if z <= -STRONG_Z:
        return "StrongBearish"
    if z <= -WEAK_Z:
        return "Bearish"
    return "Neutral"

def generate_option_plan(signal, underlying_price, conviction_z=None, risk_profile="medium"):
    """
    Returns a simple textual option trading plan (not personalized financial advice).
    Uses general strategies only and strike-selection heuristics.
    """
    if underlying_price is None:
        return {"strategy": "No market price available", "notes": ""}

    atm = nearest_strike(underlying_price)
    step = 200  # spread width example
    expiry = "nearest weekly" if risk_profile == "aggressive" else "near monthly"

    if signal in ("StrongBullish", "Bullish"):
        if signal == "StrongBullish":
            strategy = "Buy Call or Bull Call Spread"
            notes = (
                f"Buy 1 ATM Call (strike {atm}), sell 1 OTM Call (strike {atm + step}) to form a bull-call spread. "
                f"Expiry: {expiry}. Lower cost than naked call; good risk-defined plan."
            )
        else:
            strategy = "Bull Call Spread / Buy Call slightly OTM"
            notes = (
                f"Consider buying 1 slightly OTM Call (strike {atm + 50}) or a bull-call spread (buy {atm}C, sell {atm+step}C). "
                f"Expiry: {expiry}."
            )
    elif signal in ("StrongBearish", "Bearish"):
        if signal == "StrongBearish":
            strategy = "Buy Put or Bear Put Spread"
            notes = (
                f"Buy 1 ATM Put (strike {atm}), sell 1 lower Put (strike {atm - step}) to form a bear-put spread. "
                f"Expiry: {expiry}."
            )
        else:
            strategy = "Bear Put Spread / Buy Put slightly OTM"
            notes = (
                f"Consider buying 1 slightly OTM Put (strike {atm - 50}) or a bear-put spread (buy {atm}P, sell {atm-step}P). "
                f"Expiry: {expiry}."
            )
    else:
        strategy = "Range / Neutral strategies"
        notes = (
            "Flows neutral — consider iron condor or calendar spreads, or stay flat until a clearer flow emerges. "
            "Prefer defined-risk spreads over naked positions."
        )

    confidence = f"{min(95, max(40, int((abs(conviction_z or 0) / (STRONG_Z)) * 100)))}%" if conviction_z is not None else "medium"
    return {"strategy": strategy, "notes": notes, "atm": atm, "confidence": confidence}
def analyze_fii_dii(qs=None, window=ROLL_WINDOW):
    """
    Analyze FiiDii records (qs = queryset of FiiDiiRecord optionally filtered by date).
    Returns mapping: date_iso -> analysis dict:
       {
         'date': date,
         'fii_net', 'dii_net', 'total_net',
         'fii_z','dii_z','total_z',
         'signal','matched', 'intraday_change','prev_close_change',
         'suggestion': {...}
       }
    """
    if qs is None:
        qs = FiiDiiRecord.objects.all().order_by('date')

    rows = list(qs.values('date', 'fii_net', 'dii_net'))
    if not rows:
        return {}

    # Convert Decimals to floats immediately
    for row in rows:
        row['fii_net'] = float(row['fii_net'] or 0)
        row['dii_net'] = float(row['dii_net'] or 0)

    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df['total_net'] = df['fii_net'] + df['dii_net']

    # rolling z-score
    df['fii_mean'] = df['fii_net'].rolling(window, min_periods=10).mean()
    df['fii_std']  = df['fii_net'].rolling(window, min_periods=10).std().replace(0, np.nan)
    df['fii_z']    = (df['fii_net'] - df['fii_mean']) / df['fii_std']

    df['dii_mean'] = df['dii_net'].rolling(window, min_periods=10).mean()
    df['dii_std']  = df['dii_net'].rolling(window, min_periods=10).std().replace(0, np.nan)
    df['dii_z']    = (df['dii_net'] - df['dii_mean']) / df['dii_std']

    df['tot_mean'] = df['total_net'].rolling(window, min_periods=10).mean()
    df['tot_std']  = df['total_net'].rolling(window, min_periods=10).std().replace(0, np.nan)
    df['total_z']  = (df['total_net'] - df['tot_mean']) / df['tot_std']

    df = df.fillna(0)

    out = {}
    dates = df['date'].dt.date.tolist()
    market_qs = MarketRecord.objects.filter(date__in=dates, hour__isnull=True)
    market_map = {m.date: m for m in market_qs}

    # Build prev_close map
    sorted_dates = sorted(dates)
    prev_close_map = {}
    for i, d in enumerate(sorted_dates):
        prev = None
        if i > 0:
            prev = market_map.get(sorted_dates[i-1])
        prev_close_map[d] = float(prev.close) if prev else None

    for _, r in df.iterrows():
        dt = r['date'].date()
        market = market_map.get(dt)
        intraday_change = None
        prev_close_change = None

        if market:
            try:
                intraday_change = float(market.close) - float(market.open)
            except Exception:
                intraday_change = None

            prev_close = prev_close_map.get(dt)
            if prev_close is not None:
                prev_close_change = float(market.close) - prev_close

        total_z = float(r['total_z'])
        fii_z = float(r['fii_z'])
        dii_z = float(r['dii_z'])

        signal = label_from_z(total_z)

        # Matched logic
        matched = None
        if intraday_change is not None:
            if signal in ("StrongBullish", "Bullish") and intraday_change > 0:
                matched = True
            elif signal in ("StrongBearish", "Bearish") and intraday_change < 0:
                matched = True
            elif signal == "Neutral" and abs(intraday_change) < 0.05 * (float(market.open) or 1):
                matched = True
            else:
                matched = False
        elif prev_close_change is not None:
            if signal in ("StrongBullish", "Bullish") and prev_close_change > 0:
                matched = True
            elif signal in ("StrongBearish", "Bearish") and prev_close_change < 0:
                matched = True
            else:
                matched = False

        underlying_price = float(market.close) if market else None
        suggestion = generate_option_plan(signal, underlying_price, conviction_z=total_z)

        out[str(dt)] = {
            "date": dt,
            "fii_net": float(r['fii_net']),
            "dii_net": float(r['dii_net']),
            "total_net": float(r['total_net']),
            "fii_z": round(fii_z, 3),
            "dii_z": round(dii_z, 3),
            "total_z": round(total_z, 3),
            "signal": signal,
            "matched": matched,
            "intraday_change": intraday_change,
            "prev_close_change": prev_close_change,
            "suggestion": suggestion,
        }

    return out

# marketdata/analysis.py
from datetime import timedelta
from decimal import Decimal
from django.db.models import Q
from .models import MarketRecord, MarketNews, FiiDiiRecord, MarketTrap

def advanced_market_trap_analysis(start_date=None, end_date=None):
    """
    Analyze market traps combining historical data, FII/DII, and news.
    Returns a dictionary keyed by date with analysis details.
    """
    # Fetch market records
    records = MarketRecord.objects.filter(hour__isnull=True).order_by("date")
    if start_date and end_date:
        records = records.filter(date__range=[start_date, end_date])
    elif start_date:
        records = records.filter(date=start_date)

    results = {}

    for rec in records:
        date_key = str(rec.date)
        trap_info = {
            "date": rec.date,
            "trap_detected": False,
            "trap_type": "",
            "confidence": 0.0,
            "fii_dii_signal": "",
            "future_decision": "",
            "stop_loss_support": None,
            "stop_loss_resistance": None,
            "related_news": ""
        }

        # --- FII/DII Analysis ---
        fd = FiiDiiRecord.objects.filter(date=rec.date).first()
        if fd:
            net_total = fd.fii_net + fd.dii_net
            if net_total > 0:
                trap_info["fii_dii_signal"] = "Bullish"
            elif net_total < 0:
                trap_info["fii_dii_signal"] = "Bearish"
            else:
                trap_info["fii_dii_signal"] = "Neutral"

        # --- Detect Trap Patterns ---
        prev_rec = MarketRecord.objects.filter(date__lt=rec.date).order_by('-date').first()
        if prev_rec and fd:
            # Convert Decimals to float for calculations
            close = float(rec.close)
            prev_close = float(prev_rec.close)

            if close < prev_close * 0.98 and trap_info["fii_dii_signal"] == "Bullish":
                trap_info["trap_detected"] = True
                trap_info["trap_type"] = "Bullish Trap"
                trap_info["confidence"] = 0.8
                trap_info["future_decision"] = "Wait / Hedge"
                trap_info["stop_loss_support"] = round(float(rec.nifty_low) * 0.995, 2)
            elif close > prev_close * 1.02 and trap_info["fii_dii_signal"] == "Bearish":
                trap_info["trap_detected"] = True
                trap_info["trap_type"] = "Bearish Trap"
                trap_info["confidence"] = 0.8
                trap_info["future_decision"] = "Wait / Hedge"
                trap_info["stop_loss_resistance"] = round(float(rec.high) * 1.005, 2)

        # --- News Influence ---
        related_news_qs = MarketNews.objects.filter(
            published_dt__date__lte=rec.date,
            impact_score__gte=0.5
        ).order_by('-published_dt')[:5]

        trap_info["related_news"] = ", ".join([str(n.title) for n in related_news_qs if n.title])

        # --- Save / Update MarketTrap ---
        MarketTrap.objects.update_or_create(
            date=rec.date,
            defaults={
                "trap_detected": trap_info["trap_detected"],
                "trap_type": trap_info["trap_type"],
                "confidence": trap_info["confidence"],
                "fii_dii_signal": trap_info["fii_dii_signal"],
                "future_decision": trap_info["future_decision"],
                "stop_loss_support": trap_info["stop_loss_support"],
                "stop_loss_resistance": trap_info["stop_loss_resistance"],
                "related_news": trap_info["related_news"],
            }
        )

        results[date_key] = trap_info

    return results
