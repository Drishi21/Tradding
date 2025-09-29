import datetime, random

class PnLService:
    def get_daily_pnl(self, days=10):
        today = datetime.date.today()
        history = []
        base = 1000
        for i in range(days):
            date = today - datetime.timedelta(days=i)
            pnl = base + random.randint(-500, 500)
            history.append({"date": date.strftime("%Y-%m-%d"), "pnl": pnl})
        return list(reversed(history))
