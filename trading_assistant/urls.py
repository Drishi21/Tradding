from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("trades/", include("trades.urls")),
    path("marketdata/", include("marketdata.urls")),
    # path("api/accounts/", include("accounts.urls")),
    path("", include("accounts.urls")),



]
