#!/usr/bin/env bash
# Legacy recovery preview. The coordinated responder lives in apparatus.py.
set -euo pipefail

LIVE=0
NS="exp-s1-manual"
SCENARIO=""

usage() {
  cat <<'USAGE'
Usage: recovery-runbook.sh [--live] [--namespace NS] --scenario A|B|C|D|E|F|G
  This legacy entry point is dry-run only. The coordinated responder receives
  baseline declarations and observed differences, never scenario metadata.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --namespace|--ns|-n) [[ $# -ge 2 ]] || { echo "ERROR: namespace required" >&2; exit 2; }; NS="$2"; shift 2 ;;
    --scenario|-s) [[ $# -ge 2 ]] || { echo "ERROR: scenario required" >&2; exit 2; }; SCENARIO="$2"; shift 2 ;;
    --log) [[ $# -ge 2 ]] || { echo "ERROR: log path required" >&2; exit 2; }; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$NS" in
  exp-s1-manual|exp-s1-gitops|exp-s2-manual|exp-s2-gitops) ;;
  *) echo "VIOLATION: namespace not allowlisted" >&2; exit 3 ;;
esac
case "$SCENARIO" in A|B|C|D|E|F|G) ;; *) echo "ERROR: scenario must be A-G" >&2; exit 2 ;; esac
if [[ $LIVE -eq 1 ]]; then
  echo "ERROR: legacy live recovery is disabled; use scripts/apparatus.py" >&2
  exit 2
fi

if [[ "$SCENARIO" == "F" ]]; then
  echo "[DRY-RUN] F is an unmanaged visibility-boundary case; no correction or cleanup is planned"
else
  echo "[DRY-RUN] scenario=$SCENARIO namespace=$NS"
  echo "[DRY-RUN] responder would apply declared baseline fields for observed differences"
  echo "[DRY-RUN] restoration requires two consecutive common-oracle equality reads"
fi
echo "[DRY-RUN] nothing executed or written"
