#!/bin/sh
# Dashboard entrypoint — just Streamlit bound to Cloud Run's $PORT.
# All auth happens upstream at the IAP-protected HTTPS Load Balancer;
# Streamlit trusts the X-Goog-Authenticated-User-Email header it receives.
# Cloud Run ingress is locked to internal + load-balancer so nothing else
# can reach this process.

set -eu

: "${PORT:=8080}"

exec streamlit run dashboard.py \
    --server.port="${PORT}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --server.enableWebsocketCompression=false
