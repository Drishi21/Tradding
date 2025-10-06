# tradeapp/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/<str:index>/", views.trade_dashboard, name="trade_dashboard"),
    path("trade_prices_api/<str:index>/", views.trade_prices_api, name="trade_prices_api"),
    path("live_plan/<str:index>/", views.live_trade_plan, name="live_trade_plan"),
    path("option_chain/<int:strike>/", views.option_chain_api, name="option_chain_api"),
]
