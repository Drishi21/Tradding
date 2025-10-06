from django.shortcuts import render
from django.http import JsonResponse
from django.utils.timezone import localtime
from django.core.cache import cache
from requests.adapters import HTTPAdapter, Retry
import requests, yfinance as yf
from .models import TradePlan, OptionTrade

import requests, json, time
from requests.adapters import HTTPAdapter, Retry
import requests, json, time
from requests.adapters import HTTPAdapter, Retry
from django.core.cache import cache
import requests, json, time
from requests.adapters import HTTPAdapter, Retry
from django.core.cache import cache

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/option-chain",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def fetch_option_chain(index="NIFTY"):
    """
    Fetch NSE Option Chain safely with robust fallback.
    """
    cache_key = f"option_chain_{index}"
    cached = cache.get(cache_key)
    base_url = "https://www.nseindia.com"
    api_url = f"{base_url}/api/option-chain-indices?symbol={index.upper()}"

    for attempt in range(3):
        try:
            session = requests.Session()
            retries = Retry(total=2, backoff_factor=1, status_forcelist=[502, 503, 504])
            session.mount("https://", HTTPAdapter(max_retries=retries))

            # === 1️⃣ Warm-up: homepage to get valid cookies ===
            home = session.get(base_url, headers=NSE_HEADERS, timeout=10)
            if home.status_code != 200 or "nseQuoteSymbol" not in home.text:
                print(f"⚠️ Attempt {attempt+1}: Homepage failed for {index}, retrying...")
                time.sleep(2 ** attempt)
                continue  # try again

            # === 2️⃣ Option Chain API ===
            resp = session.get(api_url, headers=NSE_HEADERS, timeout=10)

            if not resp.text.strip().startswith("{"):
                print(f"⚠️ Attempt {attempt+1}: Invalid JSON for {index}, retrying...")
                time.sleep(2 ** attempt)
                continue

            data = resp.json()
            records = data.get("records", {})
            underlying = records.get("underlyingValue")
            option_data = records.get("data", [])

            if not option_data:
                print(f"⚠️ Attempt {attempt+1}: Empty option data for {index}")
                time.sleep(2 ** attempt)
                continue

            # ✅ Cache & return on success
            cache.set(cache_key, (underlying, option_data), timeout=180)
            return underlying, option_data

        except Exception as e:
            print(f"⚠️ Attempt {attempt+1} failed for {index}: {e}")
            time.sleep(2 ** attempt)

    # === 3️⃣ If all fails, fallback to cache ===
    if cached:
        print(f"✅ Using cached option chain for {index}")
        return cached

    print(f"❌ All attempts failed for {index}. No live data available.")
    return None, []



# === Get latest index price ===
def get_latest_price(index="NIFTY"):
    """Fetch current index price via Yahoo Finance."""
    symbol_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
    symbol = symbol_map.get(index, "^NSEI")
    try:
        data = yf.Ticker(symbol).history(period="1d", interval="1m")
        if not data.empty:
            return round(float(data["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"⚠️ Error fetching {index} price: {e}")
    return None


# === Update trade + option statuses ===
def update_trade_status(index="NIFTY"):
    active_trades = TradePlan.objects.filter(index=index, status="Pending")
    latest_price = get_latest_price(index)
    if not latest_price:
        return

    # Update trade plans
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

    # Update options
    _, option_data = fetch_option_chain(index)
    if not option_data:
        return
    active_opts = OptionTrade.objects.filter(trade_plan__index=index, status="Pending")

    for opt in active_opts:
        row = next((r for r in option_data if r.get("strikePrice") == opt.strike), None)
        if not row:
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


# === Generate new trade plan ===
def generate_trade_plan(price, index):
    direction = "Long" if price % 2 == 0 else "Short"
    plan = TradePlan.objects.create(
        index=index,
        level=price,
        direction=direction,
        entry_price=price,
        stop_loss=price - 25 if direction == "Long" else price + 25,
        target=price + 60 if direction == "Long" else price - 60,
        confidence=75,
    )

    # Option mapping
    _, option_data = fetch_option_chain(index)
    atm = round(price / 50) * 50
    for strike in [atm, atm + 50]:
        row = next((r for r in option_data if r.get("strikePrice") == strike), None)
        if not row:
            continue
        opt_type = "CE" if direction == "Long" else "PE"
        model_type = "CALL" if direction == "Long" else "PUT"
        ltp = row.get(opt_type, {}).get("lastPrice", 0)
        if not ltp:
            continue
        OptionTrade.objects.create(
            trade_plan=plan,
            strike=strike,
            type=model_type,
            ltp=ltp,
            stop_loss=round(ltp * 0.7, 2),
            target=round(ltp * 1.7, 2),
        )
    return plan


# === Live trade API ===
def live_trade_plan(request, index):
    price = get_latest_price(index)
    if not price:
        return JsonResponse({"error": f"Failed to fetch {index} price"})
    plan = generate_trade_plan(price, index)
    return JsonResponse({
        "time": str(localtime(plan.created_at)),
        "price": plan.level,
        "direction": plan.direction,
        "entry": plan.entry_price,
        "sl": plan.stop_loss,
        "target": plan.target,
        "confidence": plan.confidence,
        "expiry": plan.expiry.strftime("%Y-%m-%d"),
    })


# === Option Chain API (with trend detection) ===
def option_chain_api(request, strike, index="NIFTY"):
    _, option_data = fetch_option_chain(index)
    if not option_data:
        return JsonResponse({"error": f"Failed to load {index} option data"})

    chain = []
    for row in option_data:
        chain.append({
            "strike": row["strikePrice"],
            "call_ltp": row.get("CE", {}).get("lastPrice", 0),
            "put_ltp": row.get("PE", {}).get("lastPrice", 0),
            "call_oi": row.get("CE", {}).get("openInterest", 0),
            "put_oi": row.get("PE", {}).get("openInterest", 0),
        })

    snapshot = [r for r in chain if abs(r["strike"] - int(strike)) <= 300]
    prev_snapshot = cache.get(f"{index}_option_chain", {})
    trends = {}

    for row in snapshot:
        s = row["strike"]
        prev = prev_snapshot.get(s, {})
        trends[s] = {
            "call_oi_trend": "↑" if row["call_oi"] > prev.get("call_oi", 0) else "↓" if row["call_oi"] < prev.get("call_oi", 0) else "-",
            "put_oi_trend": "↑" if row["put_oi"] > prev.get("put_oi", 0) else "↓" if row["put_oi"] < prev.get("put_oi", 0) else "-",
        }

    cache.set(f"{index}_option_chain", {r["strike"]: r for r in snapshot}, timeout=300)
    return JsonResponse({"snapshot": snapshot, "trend": trends})


# === Dashboard ===
def trade_dashboard(request, index="NIFTY"):
    update_trade_status(index)

    # Use a full queryset for summary (no slicing)
    full_qs = TradePlan.objects.filter(index=index)

    # Then slice separately for recent display
    plans = full_qs.prefetch_related("options").order_by("-created_at")[:20]

    # Safe summary counts (work on full_qs)
    summary = {
        "total": full_qs.count(),
        "success": full_qs.filter(status="Hit Target").count(),
        "failed": full_qs.filter(status="Stop Loss").count(),
        "inprogress": full_qs.filter(status="Pending").count(),
    }
    summary["win_rate"] = round((summary["success"] / summary["total"]) * 100, 2) if summary["total"] else 0

    return render(request, "tradeapp/trade_dashboard.html", {
        "plans": plans,
        "index": index,
        "summary": summary,
        "live_price": get_latest_price(index),
    })


# === Live price API for refresh ===
def trade_prices_api(request, index="NIFTY"):
    return JsonResponse({"nifty": get_latest_price(index)})
