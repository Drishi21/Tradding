from growwapi import GrowwAPI
import pyotp
from decouple import config

class GrowwClient:
    def __init__(self):
        api_key = config("GROWW_API_KEY")
        api_secret = config("GROWW_API_SECRET")

        totp_gen = pyotp.TOTP(api_secret)
        totp = totp_gen.now()
        access_token = GrowwAPI.get_access_token(api_key=api_key, totp=totp)

        self.groww = GrowwAPI(access_token)

    def place_option_order(self, symbol, qty, order_type="MARKET", txn_type="BUY", price=None):
        return self.groww.place_order(
            trading_symbol=symbol,
            quantity=qty,
            validity=self.groww.VALIDITY_DAY,
            exchange=self.groww.EXCHANGE_NSE,
            segment=self.groww.SEGMENT_FNO,
            product=self.groww.PRODUCT_NRML,
            order_type=getattr(self.groww, f"ORDER_TYPE_{order_type}"),
            transaction_type=getattr(self.groww, f"TRANSACTION_TYPE_{txn_type}"),
            price=price
        )

    def get_positions(self):
        return self.groww.get_positions_for_user(segment=self.groww.SEGMENT_FNO)

    def get_orders(self):
        return self.groww.get_order_list(segment=self.groww.SEGMENT_FNO, page=0, page_size=50)

    def get_ltp(self, symbol):
        return self.groww.get_ltp(
            segment=self.groww.SEGMENT_FNO,
            exchange_trading_symbols=f"NSE_{symbol}"
        )
