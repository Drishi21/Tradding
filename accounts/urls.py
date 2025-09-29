from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("order/place/", views.place_order, name="place_order"),
    path("order/stoploss/", views.stop_loss_order, name="stop_loss_order"),
    path("orders/", views.orders_view, name="orders"),
    path("orders/<str:order_id>/cancel/", views.cancel_order_view, name="cancel_order"),
    path("orders/<str:order_id>/modify/", views.modify_order_view, name="modify_order"),
    path("options/", views.options_order_view, name="options_order"),
    path("positions/", views.positions_view, name="positions"),
    path("pnl/", views.pnl_chart_page, name="pnl_chart"),
    path("pnl/history/", views.pnl_history_view, name="pnl_history"),
]
