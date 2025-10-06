# trading_assistant/celery.py

import os
from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_assistant.settings')

app = Celery('trading_assistant')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
# 🕐 Schedule: Every morning at 8:30 AM IST
# app.conf.beat_schedule = {
#     "detect-option-reversals-daily": {
#         "task": "option_reversal.tasks.detect_option_reversals_task",
#         "schedule": crontab(hour=3, minute=0),  # UTC 03:00 = 8:30 AM IST
#     },
# }