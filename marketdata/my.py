def record_list(request):
      # ================= UPDATE DATA ==================
    if request.method == "POST" and "update_data" in request.POST:
        nifty_records = fetch_nifty_history(days=30, include_hourly=True, include_30m=True)
        fii_dii_list = fetch_fii_dii()
        fii_dii_map = {datetime.strptime(r["date"], "%Y-%m-%d").date(): r for r in fii_dii_list}

        for r in nifty_records:
            date_val = r["date"]
            fii_info = fii_dii_map.get(date_val, {})

            if r["interval"] == "1d":
                existing = MarketRecord.objects.filter(date=date_val, interval="1d").first()
                pcr_val = fetch_pcr_data() if date_val == date.today() else getattr(existing, "pcr", 0)

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
                    },
                )
            else:
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
                    },
                )
        return redirect("record_list")

    filter_option = request.GET.get("filter", "all")
    trend_filter = filter_option if filter_option in ["bullish","bearish","neutral"] else "all"

    qs = MarketRecord.objects.filter(interval="1d").order_by("-date")
    today = date.today()

    # --- Date / weekday filters ---
    if filter_option == "today":
        qs = qs.filter(date=today)
    elif filter_option == "yesterday":
        qs = qs.filter(date=today - timedelta(days=1))
    elif filter_option == "week":
        start = today - timedelta(days=today.weekday())
        qs = qs.filter(date__gte=start, date__lte=today)
    elif filter_option == "month":
        qs = qs.filter(date__year=today.year, date__month=today.month)
    elif filter_option == "3months":
        qs = qs.filter(date__gte=today - timedelta(days=90), date__lte=today)
    elif filter_option in ["monday","tuesday","wednesday","thursday","friday"]:
        weekday_map = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4}
        qs = qs.filter(date__week_day=weekday_map[filter_option]+2)  # Django: Sunday=1

    # --- Trend filter in DB ---
    if trend_filter in ["bullish","bearish","neutral"]:
        qs = qs.filter(decision__iexact=trend_filter.capitalize())

    # --- Pagination ---
    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # --- Extra calculations per page only ---
    for rec in page_obj:
        fii = rec.fii_net or 0
        dii = rec.dii_net or 0
        total_abs = abs(fii)+abs(dii)
        rec.fii_percent = round((abs(fii)/total_abs)*100,1) if total_abs>0 else 0
        rec.dii_percent = round((abs(dii)/total_abs)*100,1) if total_abs>0 else 0
        rec.bias = decide_trend_from_fii_dii(fii, dii, rec.points)

    # --- Summary stats ---
    working_days = [r for r in qs if r.date.weekday()<5]
    total_days = len(working_days)
    bullish_days = len([r for r in working_days if r.decision=="Bullish"])
    bearish_days = len([r for r in working_days if r.decision=="Bearish"])
    neutral_days = total_days - (bullish_days + bearish_days)

    context = {
        "records": page_obj,
        "filter_option": filter_option,
        "trend_filter": trend_filter,
        "bullish_percent": round((bullish_days/total_days)*100,1) if total_days else 0,
        "bearish_percent": round((bearish_days/total_days)*100,1) if total_days else 0,
        "neutral_percent": round((neutral_days/total_days)*100,1) if total_days else 0,
        "bullish_days": bullish_days,
        "bearish_days": bearish_days,
        "neutral_days": neutral_days,
        "total_days": total_days,
        "last": qs.first(),
    }
    return render(request, "marketdata/record_list.html", context)
