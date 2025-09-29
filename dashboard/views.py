import yfinance as yf
from django.shortcuts import render

def dashboard(request):
    try:
        # Nifty 50 symbol for Yahoo Finance
        nifty = yf.Ticker("^NSEI")
        nifty_price = nifty.history(period="1d")["Close"].iloc[-1]
    except Exception as e:
        nifty_price = f"Error: {e}"

    context = {"nifty_price": nifty_price}
    return render(request, "dashboard/dashboard.html", context)
