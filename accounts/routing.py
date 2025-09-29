from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/option-chain/", consumers.OptionChainConsumer.as_asgi()),
    path("ws/live-positions/", consumers.LivePositionsConsumer.as_asgi()),
]
