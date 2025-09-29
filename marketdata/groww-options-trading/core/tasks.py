from trading_platform.celery import app
from .services.groww_client import GrowwClient

groww_client = GrowwClient()

@app.task
def monitor_positions():
    positions = groww_client.get_positions()
    for pos in positions.get("positions", []):
        pnl = pos.get("net_price", 0) - pos.get("credit_price", 0)
        if pnl < -2000:  # example stop loss
            groww_client.place_option_order(
                pos["trading_symbol"], pos["quantity"], "MARKET", "SELL"
            )
