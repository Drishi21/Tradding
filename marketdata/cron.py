# marketdata/cron.py
from datetime import datetime
from .views import generate_live_prediction, validate_predictions
from .models import Prediction

def run_prediction_job():
    print("⚡ Running cron job at:", datetime.now())

    # Validate old predictions first
    validate_predictions()

    # Generate new one
    prediction = generate_live_prediction()
    if prediction:
        Prediction.objects.create(
            interval="30m",  # since we run cron every 30m
            price_at_prediction=prediction["entry"],
            predicted_trend=prediction["trend"],
            entry=prediction["entry"],
            stoploss=prediction["stoploss"],
            target=prediction["target"],
            lots=prediction["lots"],
            result=prediction["result"],
        )
        print("✅ Prediction saved:", prediction)
    else:
        print("❌ No prediction generated")
