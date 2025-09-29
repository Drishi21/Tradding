from django.db import models

class Trade(models.Model):
    OPTION_TYPE_CHOICES = [
        ("CALL", "Call Option"),
        ("PUT", "Put Option"),
    ]
    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("CLOSED", "Closed"),
    ]

    symbol = models.CharField(max_length=50, default="NIFTY50")
    strike_price = models.DecimalField(max_digits=10, decimal_places=2)
    option_type = models.CharField(max_length=4, choices=OPTION_TYPE_CHOICES)
    entry_price = models.DecimalField(max_digits=10, decimal_places=2)
    stop_loss = models.DecimalField(max_digits=10, decimal_places=2)
    target = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default="OPEN")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.symbol} {self.strike_price} {self.option_type}"
