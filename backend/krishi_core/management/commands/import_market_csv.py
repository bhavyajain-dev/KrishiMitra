import csv
import re

from django.core.management.base import BaseCommand, CommandError

from krishi_core.services.market_sync import upsert_market_records

# data.gov.in CSV headers look like "Min_x0020_Price", "Arrival_Date", "State".
_FIELDS = {
    "state": "state", "district": "district", "market": "market",
    "commodity": "commodity", "variety": "variety", "arrival_date": "arrival_date",
    "min_price": "min_price", "max_price": "max_price", "modal_price": "modal_price",
}


def _norm(header):
    h = header.strip().lower().replace("_x0020_", "_")
    return re.sub(r"[^a-z0-9]+", "_", h).strip("_")


class Command(BaseCommand):
    help = "Import mandi prices from a data.gov.in CSV download (same dataset as the API)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the downloaded CSV file")

    def handle(self, *args, csv_path, **options):
        try:
            f = open(csv_path, newline="", encoding="utf-8-sig")
        except OSError as e:
            raise CommandError(f"Cannot open {csv_path}: {e}")
        with f:
            reader = csv.DictReader(f)
            mapping = {h: _FIELDS[_norm(h)] for h in (reader.fieldnames or []) if _norm(h) in _FIELDS}
            missing = {"state", "district", "market", "commodity", "modal_price"} - set(mapping.values())
            if missing:
                raise CommandError(f"CSV is missing columns: {sorted(missing)}. Found: {reader.fieldnames}")
            total, chunk = 0, []
            for row in reader:
                chunk.append({mapping[h]: (v or "").strip() for h, v in row.items() if h in mapping})
                if len(chunk) >= 2000:
                    total += upsert_market_records(chunk)
                    chunk = []
                    self.stdout.write(f"  imported {total} rows...")
            if chunk:
                total += upsert_market_records(chunk)
        self.stdout.write(self.style.SUCCESS(f"Imported {total} mandi price rows from {csv_path}."))
