from growwapi import GrowwAPI
from django.conf import settings

class GrowwService:
    def __init__(self):
        self.api = GrowwAPI(settings.GROWW_AUTH_TOKEN)

    # ✅ Place Order
    def place_order(self, **kwargs):
        return self.api.place_order(**kwargs)

    # ✅ Modify Order
    def modify_order(self, **kwargs):
        return self.api.modify_order(**kwargs)

    # ✅ Cancel Order
    def cancel_order(self, **kwargs):
        return self.api.cancel_order(**kwargs)

    # ✅ Get Trades for Order
    def get_trades(self, groww_order_id, segment, page=0, page_size=50):
        return self.api.get_trade_list_for_order(
            groww_order_id=groww_order_id,
            segment=segment,
            page=page,
            page_size=page_size
        )

    # ✅ Get Order Status
    def get_order_status(self, groww_order_id, segment):
        return self.api.get_order_status(
            groww_order_id=groww_order_id,
            segment=segment
        )

    # ✅ Get Order List
    def get_orders(self, segment=None, page=0, page_size=50):
        return self.api.get_order_list(
            segment=segment,
            page=page,
            page_size=page_size
        )

    # ✅ Get Order Details
    def get_order_detail(self, groww_order_id, segment):
        return self.api.get_order_detail(
            groww_order_id=groww_order_id,
            segment=segment
        )
