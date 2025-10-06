# marketdata/management/commands/capture_market_snapshot.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date
from marketdata.models import MarketSnapshot, MarketSignal, SniperLevel, MarketRecord
from marketdata.views import fetch_nifty_option_chain , summarize_chain, detect_trap, estimate_profit_for_option # adjust import to where function lives

class Command(BaseCommand):
    help = "Capture market snapshot (option chain) and compute simple signals. Intended to run every 20 minutes."

    def handle(self, *args, **options):
        now = timezone.now()
        today = date.today()

        # Get market record close if available
        rec = MarketRecord.objects.filter(date=today, interval="1d").first()
        sniper = SniperLevel.objects.filter(date=today).first()

        # Fetch option chain
        try:
            meta, option_data = fetch_nifty_option_chain()
        except Exception as e:
            self.stderr.write(f"Option fetch failed: {e}")
            return

        # Determine ATM using rec or raw close from meta if available
        close_price = None
        if rec:
            close_price = float(rec.close)
            atm = round(close_price / 50) * 50
            if close_price < atm:
                atm -= 50
        else:
            # fallback: use meta if available
            if isinstance(meta, dict):
                close_price = meta.get("underlyingValue")
            elif isinstance(meta, (float, int)):
                close_price = float(meta)
            else:
                close_price = None

            try:
                atm = round(float(close_price) / 50) * 50 if close_price else None
                if close_price and close_price < atm:
                    atm -= 50
            except Exception:
                atm = None

        summary = summarize_chain(option_data, atm)

        # compute simple profit sums (e.g., hypothetical long 1 lot at previous LTP vs current)
        # For simplicity: use ltp as entry and current as same (so profit=0) — but we can compute
        # estimated short-term PnL by comparing recent two strikes near ATM.
        # We'll compute totals as sum of LTPs (cheap proxy).
        total_call_profit = round(summary["call_sum"], 2)
        total_put_profit = round(summary["put_sum"], 2)

        # get previous snapshot for comparison
        prev = MarketSnapshot.objects.order_by("-timestamp").first()

        trap_flag, trap_note = detect_trap(summary, {
            "call_vol": prev.call_volume if prev else None,
            "put_vol": prev.put_volume if prev else None,
            "call_oi": prev.call_oi if prev else None,
            "put_oi": prev.put_oi if prev else None,
            "call_sum": prev.total_call_profit if prev else None,
            "put_sum": prev.total_put_profit if prev else None,
        } if prev else None)

        # Heuristic recommendation:
        rec_text = "Monitor"
        if trap_flag:
            # if trap detected prefer avoiding new positions
            rec_text = "Avoid"
        else:
            # choose whichever side showing strength
            if summary["call_sum"] > summary["put_sum"] * 1.1:
                rec_text = "Prefer CE"
            elif summary["put_sum"] > summary["call_sum"] * 1.1:
                rec_text = "Prefer PE"

        # create snapshot row
        snap = MarketSnapshot.objects.create(
            timestamp=now,
            date=today,
            interval_minutes=20,
            close=close_price,
            atm=atm or 0,
            sniper=sniper.sniper if sniper else None,
            total_call_profit=total_call_profit,
            total_put_profit=total_put_profit,
            call_volume=summary["call_vol"],
            put_volume=summary["put_vol"],
            call_oi=summary["call_oi"],
            put_oi=summary["put_oi"],
            trap_flag=bool(trap_flag),
            trap_note=trap_note,
            recommendation=rec_text,
            raw_chain=option_data,
        )

        # Create per-strike MarketSignal for top few strikes around ATM
        strikes = sorted({r["strike"] for r in summary["rows"]})
        # choose nearest +/- 300 range
        focused = [s for s in strikes if (atm - 300) <= s <= (atm + 300)] if atm else strikes[:10]
        for r in summary["rows"]:
            strike = r["strike"]
            if strike not in focused:
                continue
            ce = r["CE"]
            pe = r["PE"]
            # simple profit estimate vs entry = ltp (0)
            est_ce_profit = estimate_profit_for_option(ce["ltp"], ce["ltp"], position="long", qty=1)
            est_pe_profit = estimate_profit_for_option(pe["ltp"], pe["ltp"], position="long", qty=1)
            # determine trap per side (example: high vol & OI drop)
            side_trap_ce = False
            side_trap_pe = False
            # store CE
            MarketSignal.objects.create(
                snapshot=snap,
                side="CE",
                strike=strike,
                ltp=ce["ltp"],
                oi=ce["oi"],
                volume=ce["vol"],
                est_profit=est_ce_profit,
                trap=side_trap_ce,
                note=""
            )
            MarketSignal.objects.create(
                snapshot=snap,
                side="PE",
                strike=strike,
                ltp=pe["ltp"],
                oi=pe["oi"],
                volume=pe["vol"],
                est_profit=est_pe_profit,
                trap=side_trap_pe,
                note=""
            )

        self.stdout.write(self.style.SUCCESS(f"Captured snapshot @ {now.isoformat()} rec={rec_text}"))
