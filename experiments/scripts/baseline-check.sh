#!/usr/bin/env bash
# Legacy baseline preview. Live measurement is coordinated by apparatus.py.
set -euo pipefail

LIVE=0
NS="exp-s1-manual"
APP=""

usage() {
  cat <<'USAGE'
Usage: baseline-check.sh [--live] [--namespace NS] [--app APP-NAME]
  This legacy entry point is dry-run only. Use scripts/apparatus.py for a
  coordinated pilot run; it requires explicit pilot context/app allowlists.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --namespace|--ns|-n) [[ $# -ge 2 ]] || { echo "ERROR: namespace required" >&2; exit 2; }; NS="$2"; shift 2 ;;
    --app) [[ $# -ge 2 ]] || { echo "ERROR: app required" >&2; exit 2; }; APP="$2"; shift 2 ;;
    --log) [[ $# -ge 2 ]] || { echo "ERROR: log path required" >&2; exit 2; }; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$NS" in
  exp-s1-manual|exp-s1-gitops|exp-s2-manual|exp-s2-gitops) ;;
  *) echo "VIOLATION: namespace not allowlisted" >&2; exit 3 ;;
esac
if [[ "$NS" == *-gitops && -z "$APP" ]]; then
  echo "ERROR: gitops preview requires --app" >&2
  exit 2
fi
if [[ $LIVE -eq 1 ]]; then
  echo "ERROR: legacy live baseline is disabled; use scripts/apparatus.py" >&2
  exit 2
fi

echo "[DRY-RUN] baseline target namespace=$NS app=${APP:-(none)}"
echo "[DRY-RUN] would validate expected inventory, ready pods, and non-empty node CPU metrics"
echo "[DRY-RUN] nothing executed or written"
