#!/usr/bin/env bash
# Legacy injection preview. Coordinated live injection is handled by apparatus.py.
set -euo pipefail

LIVE=0
NS="exp-s1-manual"
SCENARIO="all"
ORDER="random"

usage() {
  cat <<'USAGE'
Usage: drift-inject.sh [--live] [--namespace NS] [--scenario A|B|C|D|E|F|G|all]
                       [--order random|sequential]
  This legacy entry point is dry-run only. A coordinated run accepts one
  scenario and requires the pilot gates in scripts/apparatus.py.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --namespace|--ns|-n) [[ $# -ge 2 ]] || { echo "ERROR: namespace required" >&2; exit 2; }; NS="$2"; shift 2 ;;
    --scenario|-s) [[ $# -ge 2 ]] || { echo "ERROR: scenario required" >&2; exit 2; }; SCENARIO="$2"; shift 2 ;;
    --order) [[ $# -ge 2 ]] || { echo "ERROR: order required" >&2; exit 2; }; ORDER="$2"; shift 2 ;;
    --log) [[ $# -ge 2 ]] || { echo "ERROR: log path required" >&2; exit 2; }; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$NS" in
  exp-s1-manual|exp-s1-gitops|exp-s2-manual|exp-s2-gitops) ;;
  *) echo "VIOLATION: namespace not allowlisted" >&2; exit 3 ;;
esac
case "$SCENARIO" in A|B|C|D|E|F|G|all) ;; *) echo "ERROR: scenario must be A-G/all" >&2; exit 2 ;; esac
case "$ORDER" in random|sequential) ;; *) echo "ERROR: order must be random/sequential" >&2; exit 2 ;; esac
if [[ $LIVE -eq 1 ]]; then
  echo "ERROR: legacy live injection is disabled; use scripts/apparatus.py with one scenario" >&2
  exit 2
fi

if [[ "$SCENARIO" == "all" ]]; then LIST="A B C D E F G"; else LIST="$SCENARIO"; fi
echo "[DRY-RUN] injection preview namespace=$NS scenarios=[$LIST] order=$ORDER"
echo "[DRY-RUN] no commands executed; F remains a separate unmanaged visibility-boundary case"
