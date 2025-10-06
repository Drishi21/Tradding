from celery import shared_task
from .analysis import detect_option_reversals
from django.utils import timezone

@shared_task
def detect_option_reversals_task():
    """
    Runs automatically every morning before market opens.
    Detects new reversals for all major indices.
    """
    total_detected = 0
    for idx in ["NIFTY", "SENSEX", "BANKNIFTY"]:
        reversals = detect_option_reversals(index=idx, interval="1d", days=30)
        total_detected += len(reversals)
    return f"[{timezone.now()}] Detected {total_detected} new reversals."
