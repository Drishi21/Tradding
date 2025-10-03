from django.urls import path
from . import views

urlpatterns = [
    
    path("option_chain/<int:strike>/", views.option_chain_api, name="option_chain_api"),
    path("live_trade_plan/", views.live_trade_plan, name="live_trade_plan"),
    path("trade_dashboard/", views.trade_dashboard, name="trade_dashboard"),
    path("trade_prices_api/", views.trade_prices_api, name="trade_prices_api"),
    path("", views.record_list, name="record_list"),
    path('accordion/<int:rec_id>/<str:interval>/', views.accordion_view, name='accordion_view'),
    path("summary_api", views.summary_api, name="summary_api"),
    path("live-nifty/", views.live_nifty_data, name="live_nifty_data"),
    path("news/", views.news_page, name="news_page"),
    path("news/update/", views.update_news, name="update_news"),
    path("set_language/", views.set_language, name="set_language"),
    path("fii-dii/", views.fii_dii_list, name="fii_dii_list"),
    path("option-chain/", views.option_chain, name="option_chain"),
    path("ticker/", views.live_ticker, name="live_ticker"),
    path("sniper-dashboard/", views.sniper_dashboard, name="sniper_dashboard"),
    path("sniper/", views.sniper_api, name="sniper_api"),
    path("monitor/", views.market_monitor, name="market_monitor"),
    path("api/monitor/", views.market_monitor_api, name="market_monitor_api"),
 path("latest-snapshot-time/", views.latest_snapshot_time, name="latest_snapshot_time"),
]
