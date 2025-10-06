from django.urls import path
from . import views

urlpatterns = [
    # =============================
    # 📊 PRIMARY INDEX DASHBOARDS
    # =============================

    # Default route → NIFTY Dashboard
    path("", views.nifty_list, name="record_list"),

    # Index-specific daily market data
    path("nifty/", views.nifty_list, name="nifty_list"),
    path("sensex/", views.sensex_list, name="sensex_list"),
    path("banknifty/", views.banknifty_list, name="banknifty_list"),

    # Accordion data (hourly, m30, etc.)
    path("accordion/<int:rec_id>/<str:interval>/", views.accordion_view, name="accordion_view"),

    # Summary popup (multi-language)
    path("summary_api", views.summary_api, name="summary_api"),

    path("live-nifty/", views.live_nifty_data, name="live_nifty_data"),
    path("fii-dii/", views.fii_dii_list, name="fii_dii_list"),
    path("option-chain/", views.option_chain, name="option_chain"),
    path("news/", views.news_page, name="news_page"),
    path("news/update/", views.update_news, name="update_news"),
    path("set_language/", views.set_language, name="set_language"),
    path("fii-dii/", views.fii_dii_list, name="fii_dii_list"),
    path("option-chain/", views.option_chain, name="option_chain"),
    path("ticker/", views.live_ticker, name="live_ticker"),
    path("trade_dashboard/", views.trade_dashboard, name="trade_dashboard"),
    # Sniper Dashboard + API
    path("sniper-dashboard/", views.sniper_dashboard, name="sniper_dashboard"),
    path("sniper/", views.sniper_api, name="sniper_api"),

    # Market Monitor (live overview)
    path("monitor/", views.market_monitor, name="market_monitor"),
    path("api/monitor/", views.market_monitor_api, name="market_monitor_api"),

    # Latest snapshot check (for auto-refresh)
    path("latest-snapshot-time/", views.latest_snapshot_time, name="latest_snapshot_time"),
]
