from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .services.groww_client import GrowwClient

groww_client = GrowwClient()

class PlaceOptionOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        symbol = request.data.get("symbol")
        qty = int(request.data.get("qty", 50))
        order_type = request.data.get("order_type", "MARKET")
        txn_type = request.data.get("txn_type", "BUY")
        price = request.data.get("price")

        res = groww_client.place_option_order(symbol, qty, order_type, txn_type, price)
        return Response(res)

class OptionPositionsView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        res = groww_client.get_positions()
        return Response(res)

class OptionOrdersView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        res = groww_client.get_orders()
        return Response(res)

class LTPView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        symbol = request.query_params.get("symbol")
        res = groww_client.get_ltp(symbol)
        return Response(res)
