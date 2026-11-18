from django.core.management.base import BaseCommand

from krishi_core.services.market_sync import market_data_is_stale, sync_daily_market_data


class Command(BaseCommand):
    help = "Sync real APMC mandi prices from data.gov.in (needs DATAGOV_API_KEY). Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-stale", action="store_true",
            help="Skip the sync when prices were fetched within the last 24 hours.",
        )

    def handle(self, *args, **options):
        if options["if_stale"] and not market_data_is_stale():
            self.stdout.write("Market prices are fresh (< 24h old); skipping sync.")
            return
        count = sync_daily_market_data()
        if count is None:
            self.stdout.write(self.style.WARNING("Market sync skipped or failed (see log above)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Market sync complete: {count} records."))
