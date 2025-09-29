from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .services.groww_api import GrowwAPI
from .services.pnl_service import PnLService
import datetime

# def dashboard(request):
#     api = GrowwAPI()
#     account = api.get_account_info()
#     return render(request, "dashboard.html", {"account": account})
def dashboard(request):
    api = GrowwAPI()
    funds_raw = api.get_funds()
    holdings_raw = api.get_holdings()
    positions_raw = api.get_positions()

    print("DEBUG FUNDS RESPONSE:", funds_raw)
    print("DEBUG HOLDINGS RESPONSE:", holdings_raw)
    print("DEBUG POSITIONS RESPONSE:", positions_raw)

    return render(request, "dashboard.html", {
        "funds": funds_raw.get("data", {}),
        "holdings": holdings_raw.get("data", []),
        "positions": positions_raw.get("data", [])
    })

@csrf_exempt
def place_order(request):
    if request.method == "POST":
        api = GrowwAPI()
        api.place_order(
            symbol=request.POST.get("symbol"),
            qty=int(request.POST.get("quantity")),
            order_type=request.POST.get("orderType"),
            price=request.POST.get("price") or None
        )
    return redirect("orders")

@csrf_exempt
def stop_loss_order(request):
    if request.method == "POST":
        api = GrowwAPI()
        api.place_stop_loss(
            symbol=request.POST.get("symbol"),
            qty=int(request.POST.get("quantity")),
            trigger_price=float(request.POST.get("triggerPrice")),
            stop_price=float(request.POST.get("stopPrice")),
            target_price=request.POST.get("targetPrice") or None
        )
    return redirect("orders")
from django.shortcuts import render
from .services.groww_api import GrowwService


# def orders_view(request):
#     api = GrowwAPI()
#     orders_data = api.get_orders()
#     orders = orders_data.get("orders", []) if isinstance(orders_data, dict) else []
#     return render(request, "orders.html", {"orders": orders})
def orders_view(request):
    groww = GrowwService()
    orders = groww.get_orders(page=0, page_size=50)
    return render(request, "orders.html", {"orders": orders.get("order_list", [])})

@csrf_exempt
def cancel_order_view(request, order_id):
    api = GrowwAPI()
    api.cancel_order(order_id)
    return redirect("orders")

@csrf_exempt
def modify_order_view(request, order_id):
    if request.method == "POST":
        api = GrowwAPI()
        api.modify_order(order_id,
                         new_qty=request.POST.get("quantity"),
                         new_price=request.POST.get("price"))
    return redirect("orders")

def options_order_view(request):
    today = datetime.date.today()
    expiries = [(today + datetime.timedelta(days=i*7)).strftime("%Y-%m-%d") for i in range(1,5)]
    atm_strike = 19500
    strikes = [atm_strike + (i*100) for i in range(-5,6)]
    option_chain = [{"strike": s, "CE": "-", "PE": "-"} for s in strikes]

    if request.method == "POST":
        api = GrowwAPI()
        symbol = request.POST.get("symbol")
        expiry = request.POST.get("expiry").replace("-", "")
        strike = request.POST.get("strike")
        opt_type = request.POST.get("option_type")
        qty = int(request.POST.get("quantity"))
        order_type = request.POST.get("orderType")
        price = request.POST.get("price") or None
        opt_symbol = f"{symbol.upper()}{expiry}{strike}{opt_type}"
        api.place_order(symbol=opt_symbol, qty=qty, order_type=order_type, price=price)
        return redirect("orders")

    return render(request, "options.html", {"expiries": expiries, "option_chain": option_chain, "atm_strike": atm_strike})

def positions_view(request):
    api = GrowwAPI()
    holdings = api.get_holdings().get("holdings", [])
    positions = api.get_positions().get("positions", [])
    return render(request, "positions.html", {"holdings": holdings, "positions": positions})

def pnl_history_view(request):
    service = PnLService()
    history = service.get_daily_pnl(days=15)
    return JsonResponse(history, safe=False)

def pnl_chart_page(request):
    return render(request, "pnl_chart.html")
