from django.urls import path
from .views import trade_list, add_trade

urlpatterns = [
    path("", trade_list, name="trade_list"),
    path("add/", add_trade, name="add_trade"),
]
