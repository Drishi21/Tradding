from django.db import models
import datetime

def get_next_expiry():
    """Find the next Thursday (weekly expiry)."""
    today = datetime.date.today()
    days_ahead = (3 - today.weekday()) % 7  # Thursday = 3
    if days_ahead == 0:  # If today is Thursday, push to next week
        days_ahead = 7
    return today + datetime.timedelta(days=days_ahead)


class TradePlan(models.Model):
    INDEX_CHOICES = [
        ("NIFTY", "Nifty 50"),
        ("BANKNIFTY", "Bank Nifty"),
        ("SENSEX", "Sensex 30"),
    ]
    index = models.CharField(max_length=20, choices=INDEX_CHOICES, default="NIFTY")

    created_at = models.DateTimeField(auto_now_add=True)
    level = models.FloatField()
    direction = models.CharField(max_length=10, choices=[("Long", "Long"), ("Short", "Short")])
    entry_price = models.FloatField()
    stop_loss = models.FloatField()
    target = models.FloatField()
    confidence = models.FloatField()
    status = models.CharField(max_length=20, default="Pending")

    pcr = models.FloatField(null=True, blank=True)
    fii_signal = models.CharField(max_length=20, null=True, blank=True)
    dii_signal = models.CharField(max_length=20, null=True, blank=True)
    option_sentiment = models.CharField(max_length=20, null=True, blank=True)
    signals = models.JSONField(default=dict)
    expiry = models.DateField(default=get_next_expiry)

    def __str__(self):
        return f"{self.index} | {self.direction} @ {self.entry_price}"


class OptionTrade(models.Model):
    trade_plan = models.ForeignKey(TradePlan, on_delete=models.CASCADE, related_name="options")
    strike = models.IntegerField()
    type = models.CharField(max_length=4, choices=[("CALL", "CALL"), ("PUT", "PUT")])
    ltp = models.FloatField()
    stop_loss = models.FloatField()
    target = models.FloatField()
    status = models.CharField(max_length=20, default="Pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.trade_plan.index} {self.type} {self.strike} ({self.status})"
