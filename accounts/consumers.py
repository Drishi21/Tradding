import json, asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from .services.groww_api import GrowwAPI

class OptionChainConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.running = True
        self.symbol = "NIFTY"
        self.expiry = "20250925"
        self.central_strike = 19500
        self.count = 5

        while self.running:
            try:
                api = GrowwAPI()
                strikes = [self.central_strike + 100 * i for i in range(-self.count, self.count+1)]
                option_chain = []
                for s in strikes:
                    for opt_type in ("CE","PE"):
                        opt_symbol = f"{self.symbol}{self.expiry}{s}{opt_type}"
                        ltp_data = api.get_ltp("NSE", "FNO", opt_symbol)
                        option_chain.append({"strike": s, "type": opt_type, "ltp": ltp_data.get("ltp")})
                await self.send(text_data=json.dumps({"option_chain": option_chain}))
            except Exception as e:
                print("OptionChainConsumer error:", e)
            await asyncio.sleep(3)

    async def disconnect(self, close_code):
        self.running = False


class LivePositionsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.running = True
        api = GrowwAPI()

        while self.running:
            try:
                holdings = api.get_holdings().get("holdings", [])
                positions = api.get_positions().get("positions", [])
                await self.send(text_data=json.dumps({"holdings": holdings, "positions": positions}))
            except Exception as e:
                print("LivePositionsConsumer error:", e)
            await asyncio.sleep(5)

    async def disconnect(self, close_code):
        self.running = False
