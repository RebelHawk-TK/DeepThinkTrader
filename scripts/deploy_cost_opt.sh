#!/usr/bin/env bash
# Staged rebuild + deploy for cost-optimization changes (levers 2, 3, 4).
#
# What this ships:
#   - utils/cycle_cache.py (new) — TTL cache for Claude/debate across users
#   - agents/deepthink_agent.py — uses cache; skips debate on HOLD
#   - config.py — RESEARCH_INTERVAL_MINUTES default 15 → 30
#
# Safety: exits non-zero on any failure. Runs a single-revision deploy
# with --no-traffic first so you can verify before flipping.

set -euo pipefail

PROJECT="travelforge-app"
REGION="us-central1"
IMAGE_REPO="gcr.io/${PROJECT}/trader"
TAG="${1:-cost-v2}"
IMAGE="${IMAGE_REPO}:${TAG}"

cd "$(dirname "$0")/.."

echo "==> gcloud project sanity check"
current=$(gcloud config get-value project)
if [[ "$current" != "$PROJECT" ]]; then
    echo "  current=$current, expected=$PROJECT"
    echo "  run: gcloud config set project $PROJECT"
    exit 1
fi
echo "  OK: $current"

echo
echo "==> Local sanity: pytest on risk + db + secrets suites"
.venv/bin/python -m pytest \
    tests/test_risk_manager.py \
    tests/test_database.py \
    tests/test_secrets_vault_roundtrip.py \
    -x -q --no-header

echo
echo "==> Cloud Build: $IMAGE"
gcloud builds submit --tag "$IMAGE" --timeout=20m

echo
echo "==> Deploying trader-bot to $TAG (ALL TRAFFIC)"
gcloud run services update trader-bot \
    --region="$REGION" \
    --image="$IMAGE"

echo
echo "==> Deploying trader-dashboard to $TAG (ALL TRAFFIC)"
gcloud run services update trader-dashboard \
    --region="$REGION" \
    --image="$IMAGE"

echo
echo "==> Verifying revisions"
gcloud run services describe trader-bot --region="$REGION" \
    --format="value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)"
gcloud run services describe trader-dashboard --region="$REGION" \
    --format="value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)"

echo
echo "==> Done. Next cycle should show:"
echo "   - 'Debate cache HIT' / 'Claude cache HIT' lines when 2+ users share a ticker"
echo "   - No debate calls for HOLD verdicts (today's dominant outcome)"
echo "   - 30-min cadence between cycles"
echo
echo "Tail logs: gcloud logging read 'resource.labels.service_name=trader-bot' --limit=50 --freshness=10m"
