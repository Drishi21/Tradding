from django.db import models

class OptionReversal(models.Model):
    INDEX_CHOICES = [
        ("NIFTY", "Nifty 50"),
        ("SENSEX", "Sensex 30"),
        ("BANKNIFTY", "Bank Nifty"),
    ]

    index = models.CharField(max_length=10, choices=INDEX_CHOICES)
    interval = models.CharField(max_length=10, default="1d")

    reversal_date = models.DateField()
    from_trend = models.CharField(max_length=10, choices=[("Bullish", "Bullish"), ("Bearish", "Bearish")])
    to_trend = models.CharField(max_length=10, choices=[("Bullish", "Bullish"), ("Bearish", "Bearish")])

    prev_streak_days = models.IntegerField(default=0)
    new_streak_days = models.IntegerField(default=0)
    prev_change = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    new_change = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    momentum_bias = models.CharField(
        max_length=20,
        choices=[
            ("BUY_CE", "Call Bias (Buy CE)"),
            ("BUY_PE", "Put Bias (Buy PE)"),
            ("NEUTRAL", "Neutral / Avoid"),
        ],
        default="NEUTRAL"
    )

    remarks = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-reversal_date"]
        unique_together = ("index", "interval", "reversal_date", "from_trend", "to_trend")

    def __str__(self):
        return f"{self.index} {self.interval} {self.reversal_date} ({self.from_trend} → {self.to_trend})"

    @property
    def option_signal(self):
        if self.to_trend == "Bullish":
            return "BUY_CE"
        elif self.to_trend == "Bearish":
            return "BUY_PE"
        return "NEUTRAL"

    @property
    def trade_confidence(self):
        if self.momentum_bias == "BUY_CE" and self.to_trend == "Bullish":
            return "Strong Bullish"
        elif self.momentum_bias == "BUY_PE" and self.to_trend == "Bearish":
            return "Strong Bearish"
        elif self.momentum_bias == "BUY_CE" and self.to_trend == "Bearish":
            return "Weak / Conflict"
        elif self.momentum_bias == "BUY_PE" and self.to_trend == "Bullish":
            return "Weak / Conflict"
        else:
            return "Neutral"
