from django.core.management.base import BaseCommand
from marketdata.utils import fetch_nse_json, parse_and_store, NSE_HEADERS
import requests
import time

class Command(BaseCommand):
    help = "Continuously fetch and store NSE option-chain snapshots (dev only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=15,
            help="Seconds between fetches (default 15)."
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        session = requests.Session()
        session.headers.update(NSE_HEADERS)

        self.stdout.write(self.style.SUCCESS(
            f"Starting snapshot loop. Fetching every {interval}s. Ctrl+C to stop."
        ))

        try:
            while True:
                try:
                    data = fetch_nse_json(session=session)
                    saved = parse_and_store(data)
                    self.stdout.write(
                        self.style.SUCCESS(f"[OK] Saved {saved} snapshots.")
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"[ERROR] Fetch failed: {e}")
                    )
                time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopped by user."))
