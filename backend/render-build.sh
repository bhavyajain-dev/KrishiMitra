#!/usr/bin/env bash
# KrishiMitra Render Free Web Service Build Script
# Idempotent: safe to run on every deploy

set -e

echo "=== [1/7] Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [2/7] Downloading and verifying ML model artifacts ==="
python scripts/download_models.py

echo "=== [3/7] Applying database migrations ==="
python manage.py migrate --no-input

echo "=== [4/7] Syncing real mandi prices from data.gov.in (if key set and data stale) ==="
# Non-fatal: data.gov.in can be slow or down; the app also refreshes stale
# prices in the background when the Market page is opened.
python manage.py sync_market_prices --if-stale || echo "Market sync failed; continuing deploy."

echo "=== [5/7] Initializing ChromaDB vector collections ==="
python knowledge-base/scripts/init_disease_chroma.py
python knowledge-base/scripts/init_timeline_chroma.py
python knowledge-base/scripts/init_website_chroma.py

echo "=== [6/7] Collecting static assets via WhiteNoise ==="
python manage.py collectstatic --no-input

echo "=== [7/7] Render build completed successfully ==="
