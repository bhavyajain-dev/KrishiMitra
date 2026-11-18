import os
import requests
from datetime import datetime
from django.utils.timezone import make_aware
from krishi_core.models import MarketPrice

def parse_api_date(date_str):
    if not date_str:
        return datetime.now()
    try:
        day, month, year = map(int, date_str.split('/'))
        return datetime(year, month, day)
    except Exception:
        return datetime.now()

def upsert_market_records(records):
    """Bulk upsert data.gov.in-style records (dicts with state, district,
    market, commodity, variety, arrival_date, min/max/modal_price).
    One query per 1,000 rows instead of one per record; duplicates of the
    same (state, district, market, commodity, date) keep the last row."""
    now = make_aware(datetime.now())
    batch = {}
    for r in records:
        key = (r.get("state"), r.get("district"), r.get("market"),
               r.get("commodity"), r.get("arrival_date"))
        if not all(key[:4]):
            continue
        batch[key] = MarketPrice(
            state=key[0], district=key[1], market=key[2],
            commodity=key[3], arrival_date=key[4],
            variety=r.get("variety"),
            parsedDate=make_aware(parse_api_date(r.get("arrival_date"))),
            min_price=float(r.get("min_price") or 0),
            max_price=float(r.get("max_price") or 0),
            modal_price=float(r.get("modal_price") or 0),
            fetchedAt=now,
        )
    MarketPrice.objects.bulk_create(
        list(batch.values()),
        update_conflicts=True,
        unique_fields=["state", "district", "market", "commodity", "arrival_date"],
        update_fields=["variety", "parsedDate", "min_price", "max_price", "modal_price", "fetchedAt"],
        batch_size=1000,
    )
    return len(batch)


def _fetch_page(url, params, attempts=3):
    """GET one page with retries: data.gov.in often returns 502/504 or times
    out for a while. Returns the JSON dict, or None after all attempts fail."""
    import time
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, params=params, timeout=(10, 90))
            if resp.status_code >= 500:
                print(f"[MarketSyncService] data.gov.in returned HTTP {resp.status_code} (attempt {attempt}/{attempts})")
            else:
                resp.raise_for_status()
                return resp.json()
        except ValueError:
            print(f"[MarketSyncService] data.gov.in sent an invalid response (attempt {attempt}/{attempts})")
        except requests.exceptions.RequestException as e:
            print(f"[MarketSyncService] request failed: {type(e).__name__} (attempt {attempt}/{attempts})")
        if attempt < attempts:
            time.sleep(5 * attempt)
    return None


def sync_daily_market_data():
    datagov_key = os.getenv("DATAGOV_API_KEY")
    base_url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"

    if not datagov_key:
        print("[MarketSyncService] DATAGOV_API_KEY not found in environment, skipping daily sync.")
        return

    try:
        offset = 0
        limit = 500   # data.gov.in often times out on large pages
        total_processed = 0
        has_more = True

        print("[MarketSyncService] Starting daily sync of Data.gov.in Mandi prices...")

        while has_more:
            print(f"[MarketSyncService] Fetching records with offset {offset}...")
            params = {
                "api-key": datagov_key,
                "format": "json",
                "limit": limit,
                "offset": offset,
            }
            data = _fetch_page(base_url, params)
            if data is None:
                print("[MarketSyncService] data.gov.in is not responding (gave up after retries). "
                      "Their API has outages; try again later.")
                return total_processed or None
            records = data.get("records", [])

            if not records:
                has_more = False
                break

            upsert_market_records(records)

            total_processed += len(records)
            print(f"[MarketSyncService] Successfully synced batch. Total processed so far: {total_processed}")

            if len(records) < limit:
                has_more = False
            else:
                offset += limit

        print(f"\n[MarketSyncService] ✅ Daily sync complete! Total records updated/inserted: {total_processed}")
        return total_processed

    except Exception as e:
        # Don't echo the request URL: it contains the api-key query parameter.
        print(f"[MarketSyncService] Sync failed: {type(e).__name__}")
        return None


# ── Refresh-when-stale (works on hosts that sleep, e.g. Render free tier) ─────
# A 2 AM cron never fires while the instance is asleep, so the market endpoints
# call maybe_refresh_in_background(): if the newest price is older than
# MARKET_STALE_HOURS, one background thread re-syncs while the request returns
# the current data immediately.
import logging
import threading
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

MARKET_STALE_HOURS = 24
_refresh_lock = threading.Lock()
_refresh_running = False


def market_data_is_stale():
    latest = MarketPrice.objects.order_by("-fetchedAt").values_list("fetchedAt", flat=True).first()
    if latest is None:
        return True
    return timezone.now() - latest > timedelta(hours=MARKET_STALE_HOURS)


def maybe_refresh_in_background():
    """Start one background sync if data is stale and a key is configured.

    Returns True when a refresh is running (started now or already running).
    """
    global _refresh_running
    if not os.getenv("DATAGOV_API_KEY"):
        return False
    with _refresh_lock:
        if _refresh_running:
            return True
        try:
            if not market_data_is_stale():
                return False
        except Exception:
            logger.warning("Could not check market data freshness", exc_info=True)
            return False
        _refresh_running = True

    def _run():
        global _refresh_running
        from django.db import connection
        try:
            sync_daily_market_data()
        finally:
            connection.close()  # thread-local DB connection
            with _refresh_lock:
                _refresh_running = False

    threading.Thread(target=_run, name="market-sync", daemon=True).start()
    return True
