#!/bin/sh
# Isolated local resources only. Never deletes volumes or touches other projects.
set -eu
cd "$(dirname "$0")/.."
export DEMO_REVISION
DEMO_REVISION=$(git rev-parse HEAD)
mkdir -p docker-check-results/pending-update
compose() { docker compose -f compose.pending-demo.yaml "$@"; }
# Compose start can restart the completed seed dependency. Resume only the
# already-created Indexer container so the updated fixture is not reset.
resume_indexer() { docker start "$(compose ps --all -q indexer)"; }
if [ -f docker-check-results/pending-update/pending-update.json ]; then
  cp docker-check-results/pending-update/pending-update.json "docker-check-results/pending-update/previous-$(date -u +%Y%m%dT%H%M%SZ).json"
fi
compose build runner
compose up -d rabbitmq seed collector relay indexer retrieval answer gateway
compose run --rm --no-deps runner python -m scripts.demo_pending_update before
compose stop indexer
# Always resume this demo's Indexer if the pending check fails or is interrupted.
trap 'resume_indexer' EXIT HUP INT TERM
compose run --rm --no-deps runner python -m scripts.demo_pending_update pending
resume_indexer
compose run --rm --no-deps runner python -m scripts.demo_pending_update after
trap - EXIT HUP INT TERM
printf '\nDemo passed. Results: docker-check-results/pending-update/pending-update.json\n'
printf 'Gateway API: http://localhost:8091/docs\n'
