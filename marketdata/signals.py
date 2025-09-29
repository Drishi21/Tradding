from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import FiiDiiRecord, MarketRecord

@receiver(post_save, sender=FiiDiiRecord)
def analyze_fii_dii(sender, instance, created, **kwargs):
    """
    After saving FiiDiiRecord, calculate z-score, 
    check match with MarketRecord, and store suggestion.
    """
    total_net = instance.fii_net + instance.dii_net

    # 1. Normalization (simple scaling)
    instance.total_z = round(total_net / 1000.0, 2)

    # 2. Check match with MarketRecord
    try:
        market = MarketRecord.objects.get(date=instance.date)
        if (total_net > 0 and market.decision == "Bullish") or \
           (total_net < 0 and market.decision == "Bearish"):
            instance.matched = True
            instance.suggestion_text = "✅ FII+DII aligned with market → Trend confirmed."
        else:
            instance.matched = False
            instance.suggestion_text = "⚠️ Divergence detected → Trade cautiously."
    except MarketRecord.DoesNotExist:
        instance.suggestion_text = "ℹ️ No MarketRecord available."

    # Save updated fields
    instance.save(update_fields=["total_z", "matched", "suggestion_text"])
