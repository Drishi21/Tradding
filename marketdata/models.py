# marketdata/models.py
from django.db import models

# -------------------------------
# Market Record Model
# -------------------------------
from django.db import models

class MarketRecord(models.Model):
    date = models.DateField()
    hour = models.TimeField(blank=True, null=True)
    interval = models.CharField(max_length=10)

    nifty_open = models.DecimalField(max_digits=10, decimal_places=2)
    nifty_high = models.DecimalField(max_digits=10, decimal_places=2)
    nifty_low = models.DecimalField(max_digits=10, decimal_places=2)
    nifty_close = models.DecimalField(max_digits=10, decimal_places=2)
    points = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    fii_buy = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fii_sell = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fii_net = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    dii_buy = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    dii_sell = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    dii_net = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    pcr = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    global_markets = models.TextField(default="", blank=True)
    important_news = models.TextField(default="", blank=True)

    summary_en = models.TextField(blank=True, null=True)
    summary_hi = models.TextField(blank=True, null=True)
    summary_te = models.TextField(blank=True, null=True)
    summary_ta = models.TextField(blank=True, null=True)
    summary_kn = models.TextField(blank=True, null=True)

    decision = models.CharField(
        max_length=10,
        choices=[("Bullish", "Bullish"), ("Bearish", "Bearish"), ("Neutral", "Neutral")],
        default="Neutral"
    )

    class Meta:
        unique_together = ("date", "hour", "interval")
        ordering = ["-date", "hour"]

    def __str__(self):
        return f"{self.date} {self.hour or ''} ({self.interval})"

    @property
    def calculated_decision(self):
        if self.points > 0:
            return "Bullish"
        elif self.points < 0:
            return "Bearish"
        return "Neutral"

    # ---- Properties ----
    @property
    def hourly_set_calculated(self):
        return self._get_interval_records("1h")

    @property
    def m30_set_calculated(self):
        return self._get_interval_records("30m")

    @property
    def m5_set_calculated(self):
        return self._get_interval_records("5m")

    @property
    def m2_set_calculated(self):
        return self._get_interval_records("2m")

    # ---- Internal helper ----
    def _get_interval_records(self, interval):
        qs = MarketRecord.objects.filter(date=self.date, interval=interval).order_by("hour")
        prev_close = None
        for r in qs:
            r.points = 0 if prev_close is None else round(r.nifty_close - prev_close, 2)
            prev_close = r.nifty_close
        return qs
# models.py
import datetime
from django.db import models

def get_next_expiry():
    today = datetime.date.today()
    # Nifty weekly expiry is Thursday
    days_ahead = (3 - today.weekday()) % 7   # Monday=0 ... Thursday=3
    if days_ahead == 0:   # If today is Thursday, push to next week
        days_ahead = 7
    return today + datetime.timedelta(days=days_ahead)

class TradePlan(models.Model):
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

    # ✅ New field
    expiry = models.DateField(default=get_next_expiry)

class OptionTrade(models.Model):
    trade_plan = models.ForeignKey(TradePlan, on_delete=models.CASCADE, related_name="options")
    strike = models.IntegerField()
    type = models.CharField(max_length=4, choices=[("CALL","CALL"),("PUT","PUT")])
    ltp = models.FloatField()
    stop_loss = models.FloatField()
    target = models.FloatField()
    status = models.CharField(max_length=20, default="Pending")
    created_at = models.DateTimeField(auto_now_add=True)


class Prediction(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    interval = models.CharField(
        max_length=10,
        choices=[("30m", "30 Minutes"), ("1h", "Hourly"), ("1d", "Daily")]
    )
    strike = models.IntegerField(default=0)
    price_at_prediction = models.DecimalField(max_digits=10, decimal_places=2)

    predicted_trend = models.CharField(
        max_length=10,
        choices=[("Bullish", "Bullish"), ("Bearish", "Bearish"), ("Neutral", "Neutral")]
    )

    entry = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stoploss = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    target = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    lots = models.CharField(max_length=20, default="Min 1 / Max 5")

    result = models.CharField(
        max_length=10,
        choices=[("Pending", "Pending"), ("Profit", "Profit"), ("Loss", "Loss"), ("Neutral", "Neutral")],
        default="Pending"
    )

    def __str__(self):
        return f"{self.timestamp} - {self.interval} - {self.predicted_trend} ({self.result})"
from django.db import models

class MarketNews(models.Model):
    # --- Basic fields ---
    title = models.CharField(max_length=500)
    content = models.TextField(blank=True, null=True)
    source = models.CharField(max_length=200, blank=True, null=True)
    published_dt = models.DateTimeField(null=True, blank=True)
    link = models.URLField(max_length=500, blank=True, null=True)

    # --- Sentiment / Impact ---
    sentiment = models.CharField(
        max_length=10,
        choices=[('Positive', 'Positive'), ('Negative', 'Negative'), ('Neutral', 'Neutral')],
        default='Neutral'
    )
    impact_score = models.FloatField(default=0.0)  # -1 strong negative, +1 strong positive
    summary = models.TextField(blank=True, null=True)  # short actionable summary

    # --- Sector tagging (Auto, IT, Banking etc.) ---
    sectors = models.JSONField(default=list, blank=True)  
    # ✅ Stores detected sectors as a list ["Banking", "IT"]

    # --- Pre-translated fields ---
    title_te = models.TextField(blank=True, null=True)
    title_hi = models.TextField(blank=True, null=True)
    title_ta = models.TextField(blank=True, null=True)
    title_kn = models.TextField(blank=True, null=True)
    title_ml = models.TextField(blank=True, null=True)

    content_te = models.TextField(blank=True, null=True)
    content_hi = models.TextField(blank=True, null=True)
    content_ta = models.TextField(blank=True, null=True)
    content_kn = models.TextField(blank=True, null=True)
    content_ml = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-published_dt"]
        indexes = [
            models.Index(fields=["published_dt"]),
            models.Index(fields=["sentiment"]),
            models.Index(fields=["impact_score"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.sentiment}, {self.published_dt.date() if self.published_dt else ''})"

# marketdata/models.py

class FiiDiiRecord(models.Model):
    date = models.DateField(unique=True)
    fii_buy = models.FloatField()
    fii_sell = models.FloatField()
    fii_net = models.FloatField()
    dii_buy = models.FloatField()
    dii_sell = models.FloatField()
    dii_net = models.FloatField()

    # --- new fields ---
    total_z = models.FloatField(default=0.0, help_text="Normalized score of fii+dii net")
    matched = models.BooleanField(default=False, help_text="MarketRecord decision matches impact or not")
    suggestion_text = models.TextField(blank=True, null=True, help_text="Trading suggestion")

    @property
    def market_impact(self):
        total_net = self.fii_net + self.dii_net
        if total_net > 0:
            return "Bullish 📈"
        elif total_net < 0:
            return "Bearish 📉"
        return "Neutral ➖"

    def __str__(self):
        return f"{self.date} | FII Net: {self.fii_net} | DII Net: {self.dii_net}"
class MarketTrap(models.Model):
    date = models.DateField()
    trap_detected = models.BooleanField(default=False)
    trap_type = models.CharField(max_length=50, blank=True)
    confidence = models.FloatField(default=0.0)
    fii_dii_signal = models.CharField(max_length=50, blank=True)
    future_decision = models.CharField(max_length=50, blank=True)
    stop_loss_support = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stop_loss_resistance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    related_news = models.TextField(blank=True, null=True) 
    
    def __str__(self):
        return f"{self.date} | Trap: {self.trap_detected} | Type: {self.trap_type} | Decision: {self.future_decision}"
class OptionChain(models.Model):
    strike_price = models.DecimalField(max_digits=10, decimal_places=2)
    call_ltp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    call_oi = models.IntegerField(null=True, blank=True)
    call_iv = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    put_ltp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    put_oi = models.IntegerField(null=True, blank=True)
    put_iv = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

class Order(models.Model):
    ORDER_TYPES = (
        ("BUY", "Buy"),
        ("SELL", "Sell"),
    )
    INSTRUMENT_TYPES = (
        ("OPTION", "Option"),
        ("EQUITY", "Equity"),
    )
    STATUS_CHOICES = (
        ("OPEN", "Open"),
        ("EXECUTED", "Executed"),
        ("CANCELLED", "Cancelled"),
    )

    symbol = models.CharField(max_length=50)          # e.g. NIFTY23SEP18500CE
    order_type = models.CharField(max_length=4, choices=ORDER_TYPES)
    instrument_type = models.CharField(max_length=10, choices=INSTRUMENT_TYPES)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="OPEN")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.order_type} {self.symbol} x{self.quantity} @ {self.price}"


class StrategyStats(models.Model):
    strategy_name = models.CharField(max_length=50, unique=True)
    lookback_days = models.IntegerField(default=30)
    win_rate = models.FloatField(default=0.0)
    avg_pnl = models.FloatField(default=0.0)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.strategy_name} ({self.win_rate}%)"


class IntradaySlotStats(models.Model):
    slot_time = models.TimeField()  # e.g. 09:30, 10:00
    lookback_days = models.IntegerField(default=30)
    win_rate = models.FloatField(default=0.0)
    avg_pts = models.FloatField(default=0.0)
    direction = models.CharField(
        max_length=10,
        choices=[("up", "Up"), ("down", "Down"), ("neutral", "Neutral")],
        default="neutral"
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("slot_time", "lookback_days")

    def __str__(self):
        return f"{self.slot_time} ({self.win_rate}%)"
# marketdata/models.py
from django.db import models
class SniperLevel(models.Model):
    date = models.DateField(unique=True)
    close_price = models.FloatField()
    atm = models.IntegerField()
    sniper = models.FloatField()
    upper = models.FloatField()
    lower = models.FloatField()
    upper_double = models.FloatField()
    lower_double = models.FloatField()
    bias = models.CharField(max_length=20, default="Neutral")  # ✅ NEW
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} ATM:{self.atm} Sniper:{self.sniper}"
# 
class SniperTrade(models.Model):
    sniper = models.ForeignKey(SniperLevel, related_name="trades", on_delete=models.CASCADE)
    side = models.CharField(max_length=4)             # "CE" / "PE"
    strike = models.IntegerField()
    entry = models.FloatField()
    stoploss = models.FloatField()
    target1 = models.FloatField()
    target2 = models.FloatField(null=True, blank=True)
    risk_reward = models.CharField(max_length=32, null=True, blank=True)
    confidence = models.IntegerField(default=50)     # 0-100
    note = models.TextField(null=True, blank=True)
    action = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True) 

    class Meta:
        ordering = ["-sniper__date", "strike", "side"]

    def __str__(self):
        return f"{self.side}@{self.strike} ({self.confidence}%)"

class MarketSnapshot(models.Model):
    """
    Snapshot captured every N minutes (20m) containing summary metrics and JSON option snapshot.
    """
    timestamp = models.DateTimeField()            # when snapshot was taken (timezone-aware)
    date = models.DateField()                     # trading date (date component)
    interval_minutes = models.IntegerField(default=20)

    # quick numeric fields
    nifty_close = models.FloatField(null=True, blank=True)
    atm = models.IntegerField(null=True, blank=True)
    sniper = models.FloatField(null=True, blank=True)

    # summary CE/PE PnL numbers (estimates)
    total_call_profit = models.FloatField(null=True, blank=True)   # hypothetical profit for short/long basket
    total_put_profit = models.FloatField(null=True, blank=True)

    call_volume = models.BigIntegerField(null=True, blank=True)
    put_volume = models.BigIntegerField(null=True, blank=True)
    call_oi = models.BigIntegerField(null=True, blank=True)
    put_oi = models.BigIntegerField(null=True, blank=True)

    # flags / heuristics
    trap_flag = models.BooleanField(default=False)    # True if heuristic trap detected
    trap_note = models.TextField(blank=True, null=True)

    # recommendation: Take / Avoid / Monitor
    recommendation = models.CharField(max_length=20, default="Monitor")

    # store full raw option chain (small JSON) for later debugging
    raw_chain = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"Snapshot {self.timestamp.isoformat()} rec={self.recommendation}"
class MarketSignal(models.Model):
    snapshot = models.ForeignKey(MarketSnapshot, related_name="signals", on_delete=models.CASCADE)
    side = models.CharField(max_length=2)  # "CE" / "PE"
    strike = models.IntegerField()
    ltp = models.FloatField()
    oi = models.BigIntegerField(null=True, blank=True)
    volume = models.BigIntegerField(null=True, blank=True)
    est_profit = models.FloatField(null=True, blank=True)   # estimated profit if taken now
    trap = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["-snapshot__timestamp", "side", "strike"]

    def __str__(self):
        return f"{self.side}@{self.strike} ({self.snapshot.timestamp:%H:%M})"
