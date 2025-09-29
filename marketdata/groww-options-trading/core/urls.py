from django.urls import path
from .views import PlaceOptionOrderView, OptionPositionsView, OptionOrdersView, LTPView

urlpatterns = [
    path("options/order/", PlaceOptionOrderView.as_view()),
    path("options/positions/", OptionPositionsView.as_view()),
    path("options/orders/", OptionOrdersView.as_view()),
    path("options/ltp/", LTPView.as_view()),
]
