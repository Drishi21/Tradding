from django.db import models
from django.contrib.auth.models import User

class OptionChainData(models.Model):
    symbol = models.CharField(max_length=50)
    strike_price = models.DecimalField(max_digits=10, decimal_places=2)
    option_type = models.CharField(max_length=2, choices=[("CE", "Call"), ("PE", "Put")])
    expiry = models.DateField()
    oi = models.BigIntegerField()
    change_in_oi = models.BigIntegerField()
    iv = models.FloatField()
    ltp = models.FloatField()
    date = models.DateField()
    time = models.TimeField()

class Orders(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    symbol = models.CharField(max_length=50)
    order_type = models.CharField(max_length=4, choices=[("BUY", "Buy"), ("SELL", "Sell")])
    option_type = models.CharField(max_length=2, choices=[("CE", "Call"), ("PE", "Put")])
    strike_price = models.DecimalField(max_digits=10, decimal_places=2)
    expiry = models.DateField()
    qty = models.IntegerField()
    status = models.CharField(
        max_length=20,
        choices=[("open", "Open"), ("executed", "Executed"), ("closed", "Closed")],
        default="open"
    )
    created_at = models.DateTimeField(auto_now_add=True)
