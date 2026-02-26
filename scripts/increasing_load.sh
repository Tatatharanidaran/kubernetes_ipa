#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-default}"
LOADGEN_TARGET="${2:-deploy/loadgen}"
TARGET_URL="${3:-http://js-app.${NAMESPACE}.svc.cluster.local:8080}"

log_load() {
  printf "[LOAD-GENERATOR] %s\n" "$1"
}

cleanup() {
  log_load "Stopping progressive traffic loop."
  exit 0
}

trap cleanup INT TERM

log_load "Starting progressive load against ${TARGET_URL} via ${LOADGEN_TARGET} in namespace ${NAMESPACE}"

kubectl exec -n "$NAMESPACE" "$LOADGEN_TARGET" -- sh -c '
target_url="$1"

run_stage() {
  rps="$1"
  seconds="$2"
  elapsed=0
  while [ "$elapsed" -lt "$seconds" ]; do
    i=0
    while [ "$i" -lt "$rps" ]; do
      wget -qO- "$target_url" >/dev/null 2>&1 &
      i=$((i + 1))
    done
    wait
    elapsed=$((elapsed + 1))
    sleep 1
  done
}

while true; do
  run_stage 5 20
  run_stage 20 20
  run_stage 50 20
  run_stage 100 30
done
' -- "$TARGET_URL"
