# Consolidated record_list function with all helper functions integrated

def consolidated_record_list(request):
    """
    Consolidated record_list function that integrates all helper functions
    into a single, more maintainable function.
    """
    
    # =================== HELPER FUNCTIONS (INLINE) ===================
    
    def fetch_and_update_market_data():
        """Fetch and update market data - consolidated from multiple functions"""
        try:
            # Fetch NIFTY history
            import yfinance as yf
            from datetime import datetime, timedelta, time
            import pytz
            
            ist = pytz.timezone("Asia/Kolkata")
            ticker = yf.Ticker("^NSEI")
            records = []
            
            # Daily data
            df_daily = ticker.history(period="30d", interval="1d")
            prev_close = None
            
            for ts, row in df_daily.iterrows():
                py_dt = pd.to_datetime(ts).to_pydatetime()
                close = float(row["Close"])
                points = 0 if prev_close is None else round(close - prev_close, 2)
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
                prev_close = close
            
            # Fetch FII/DII data
            import requests
            from bs4 import BeautifulSoup
            import json
            
            try:
                url = "https://groww.in/fii-dii-data"
                headers = {"User-Agent": "Mozilla/5.0"}
                r = requests.get(url, headers=headers)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
                data = json.loads(script_tag.string)
                fii_dii_data = data["props"]["pageProps"]["initialData"]
                
                fii_dii_map = {}
                for row in fii_dii_data:
                    date_key = datetime.strptime(row["date"], "%Y-%m-%d").date()
                    fii_dii_map[date_key] = {
                        "fii_net": float(row["fii"]["netBuySell"]),
                        "dii_net": float(row["dii"]["netBuySell"]),
                        "fii_buy": float(row["fii"]["grossBuy"]),
                        "fii_sell": float(row["fii"]["grossSell"]),
                        "dii_buy": float(row["dii"]["grossBuy"]),
                        "dii_sell": float(row["dii"]["grossSell"]),
                    }
            except Exception:
                fii_dii_map = {}
            
            # Fetch PCR data
            def get_pcr():
                try:
                    session = requests.Session()
                    session.get("https://www.nseindia.com", headers={"User-Agent": "Mozilla/5.0"})
                    res = session.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY", 
                                    headers={"User-Agent": "Mozilla/5.0"})
                    data = res.json()
                    ce_oi = sum([d["CE"]["openInterest"] for d in data["records"]["data"] if "CE" in d])
                    pe_oi = sum([d["PE"]["openInterest"] for d in data["records"]["data"] if "PE" in d])
                    return round(pe_oi / ce_oi, 2) if ce_oi > 0 else 0
                except Exception:
                    return 0
            
            # Update database
            from .models import MarketRecord
            from datetime import date
            
            for r in records:
                date_val = r["date"]
                fii_info = fii_dii_map.get(date_val, {})
                
                if r["interval"] == "1d":
                    existing = MarketRecord.objects.filter(date=date_val, interval="1d").first()
                    pcr_val = get_pcr() if date_val == date.today() else getattr(existing, "pcr", 0)
                    
                    MarketRecord.objects.update_or_create(
                        date=date_val,
                        hour=None,
                        interval="1d",
                        defaults={
                            "open": r["open"],
                            "high": r["high"],
                            "nifty_low": r["low"],
                            "close": r["close"],
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
                        },
                    )
            
            return True
        except Exception as e:
            logger.error(f"Error updating market data: {e}")
            return False
    
    def calculate_trend_bias(fii_net, dii_net, price_points):
        """Calculate market trend from FII/DII flows and price movement"""
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
    
    def apply_date_filters(queryset, filter_option):
        """Apply date-based filters to queryset"""
        from datetime import date, timedelta
        
        today = date.today()
        
        if filter_option == "today":
            return queryset.filter(date=today)
        elif filter_option == "yesterday":
            return queryset.filter(date=today - timedelta(days=1))
        elif filter_option == "week":
            start_of_week = today - timedelta(days=today.weekday())
            return queryset.filter(date__gte=start_of_week, date__lte=today)
        elif filter_option == "month":
            return queryset.filter(date__year=today.year, date__month=today.month)
        elif filter_option == "3months":
            return queryset.filter(date__gte=today - timedelta(days=90), date__lte=today)
        elif filter_option in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
            weekday_map = {"monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6}
            return queryset.filter(date__week_day=weekday_map[filter_option])
        else:
            return queryset
    
    def calculate_summary_stats(records):
        """Calculate summary statistics for records"""
        working_days = [r for r in records if r.date.weekday() < 5]
        total_days = len(working_days)
        bullish_days = len([r for r in working_days if r.calculated_decision == "Bullish"])
        bearish_days = len([r for r in working_days if r.calculated_decision == "Bearish"])
        neutral_days = total_days - (bullish_days + bearish_days)
        
        return {
            "total_days": total_days,
            "bullish_days": bullish_days,
            "bearish_days": bearish_days,
            "neutral_days": neutral_days,
            "bullish_percent": round((bullish_days/total_days)*100, 1) if total_days else 0,
            "bearish_percent": round((bearish_days/total_days)*100, 1) if total_days else 0,
            "neutral_percent": round((neutral_days/total_days)*100, 1) if total_days else 0,
        }
    
    # =================== MAIN FUNCTION LOGIC ===================
    
    from django.shortcuts import render, redirect
    from django.core.paginator import Paginator
    from django.core.cache import cache
    from .models import MarketRecord
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Get request parameters
    filter_option = request.GET.get("filter", "all")
    trend_filter = filter_option if filter_option in ["bullish", "bearish", "neutral"] else "all"
    page_number = request.GET.get("page", 1)
    
    # Check cache first
    page_cache_key = f"record_list:{filter_option}:{trend_filter}:{page_number}"
    cached_response = cache.get(page_cache_key)
    if cached_response:
        return cached_response
    
    # Handle data update request
    if request.method == "POST" and "update_data" in request.POST:
        if fetch_and_update_market_data():
            logger.info("Market data updated successfully")
        else:
            logger.error("Failed to update market data")
        return redirect("record_list")
    
    # Get base queryset
    qs = MarketRecord.objects.filter(interval="1d").order_by("-date")
    
    # Apply date filters
    qs = apply_date_filters(qs, filter_option)
    
    # Convert to list for trend filtering
    all_records = list(qs)
    
    # Apply trend filters
    if trend_filter == "bullish":
        all_records = [r for r in all_records if r.calculated_decision == "Bullish"]
    elif trend_filter == "bearish":
        all_records = [r for r in all_records if r.calculated_decision == "Bearish"]
    elif trend_filter == "neutral":
        all_records = [r for r in all_records if r.calculated_decision == "Neutral"]
    
    # Pagination
    paginator = Paginator(all_records, 25)
    page_obj = paginator.get_page(page_number)
    
    # Calculate additional fields for each record
    for rec in page_obj:
        fii = rec.fii_net or 0
        dii = rec.dii_net or 0
        points = rec.points or 0
        rec.bias = calculate_trend_bias(fii, dii, points)
        total_abs = abs(fii) + abs(dii)
        rec.fii_percent = round((abs(fii)/total_abs)*100, 1) if total_abs > 0 else 0
        rec.dii_percent = round((abs(dii)/total_abs)*100, 1) if total_abs > 0 else 0
        rec.final_decision = rec.calculated_decision
    
    # Calculate summary statistics (with caching)
    summary_cache_key = f"summary:{filter_option}:{trend_filter}"
    summary = cache.get(summary_cache_key)
    
    if not summary:
        summary = calculate_summary_stats(all_records)
        cache.set(summary_cache_key, summary, 600)
    
    # Prepare context
    context = {
        "records": page_obj,
        "filter_option": filter_option,
        "trend_filter": trend_filter,
        "last": all_records[0] if all_records else None,
        **summary,
    }
    
    # Render and cache response
    response = render(request, "marketdata/record_list.html", context)
    cache.set(page_cache_key, response, 600)  # cache for 10 minutes
    return response
