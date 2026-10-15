#!/usr/bin/env bash
# Legacy synthetic CSV preview. New measurements use apparatus.py JSON summaries.
set -euo pipefail

LIVE=0
SAMPLE=0
SUBJECT="s1"
ENV="manual"
SCENARIO="A"
REP="1"
NS="exp-s1-manual"
APP=""
T0=""
OUT=""

usage() {
  cat <<'USAGE'
Usage: metrics-collect.sh [--live] [--live-dryrun] [--subject s1|s2]
       [--env manual|gitops] [--scenario A-G] [--rep N] [--namespace NS]
       [--app APP] [--t0 EPOCH] [--output FILE.csv]
  Default is a no-command/no-write preview. --live-dryrun appends the legacy
  synthetic CSV example. Legacy --live collection is disabled; use apparatus.py.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --live-dryrun) SAMPLE=1; shift ;;
    --subject) [[ $# -ge 2 ]] || { echo "ERROR: subject required" >&2; exit 2; }; SUBJECT="$2"; shift 2 ;;
    --env) [[ $# -ge 2 ]] || { echo "ERROR: environment required" >&2; exit 2; }; ENV="$2"; shift 2 ;;
    --scenario|-s) [[ $# -ge 2 ]] || { echo "ERROR: scenario required" >&2; exit 2; }; SCENARIO="$2"; shift 2 ;;
    --rep) [[ $# -ge 2 ]] || { echo "ERROR: repetition required" >&2; exit 2; }; REP="$2"; shift 2 ;;
    --namespace|--ns|-n) [[ $# -ge 2 ]] || { echo "ERROR: namespace required" >&2; exit 2; }; NS="$2"; shift 2 ;;
    --app) [[ $# -ge 2 ]] || { echo "ERROR: app required" >&2; exit 2; }; APP="$2"; shift 2 ;;
    --t0) [[ $# -ge 2 ]] || { echo "ERROR: t0 required" >&2; exit 2; }; T0="$2"; shift 2 ;;
    --output|-o) [[ $# -ge 2 ]] || { echo "ERROR: output path required" >&2; exit 2; }; OUT="$2"; shift 2 ;;
    --timeout|--runbook-log|--kubectl-cmds|--notes) [[ $# -ge 2 ]] || { echo "ERROR: value required for $1" >&2; exit 2; }; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$SUBJECT:$ENV:$NS" in
  s1:manual:exp-s1-manual|s1:gitops:exp-s1-gitops|s2:manual:exp-s2-manual|s2:gitops:exp-s2-gitops) ;;
  *) echo "VIOLATION: subject/environment/namespace mismatch" >&2; exit 3 ;;
esac
case "$SCENARIO" in A|B|C|D|E|F|G) ;; *) echo "ERROR: scenario must be A-G" >&2; exit 2 ;; esac
[[ "$REP" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: rep must be a positive integer" >&2; exit 2; }
if [[ "$ENV" == "gitops" && -z "$APP" ]]; then echo "ERROR: gitops requires --app" >&2; exit 2; fi
if [[ "$ENV" == "manual" && -n "$APP" ]]; then echo "ERROR: manual does not accept --app" >&2; exit 2; fi
if [[ $LIVE -eq 1 ]]; then
  echo "ERROR: legacy live collection is disabled; use scripts/apparatus.py" >&2
  exit 2
fi

HEADER="subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes"
if [[ $SAMPLE -eq 1 ]]; then
  [[ -n "$T0" ]] || T0="$(date +%s)"
  ROW="$SUBJECT,$ENV,$SCENARIO,$REP,$T0,$T0,$T0,$T0,100,0,100,0,DRYRUN-sample-tidak-menyentuh-klaster"
  if [[ -n "$OUT" ]]; then
    [[ -f "$OUT" ]] || printf '%s\n' "$HEADER" >"$OUT"
    printf '%s\n' "$ROW" >>"$OUT"
    echo "[live-dryrun] wrote legacy sample row to $OUT"
  else
    printf '%s\n%s\n' "$HEADER" "$ROW"
  fi
  exit 0
fi

echo "[DRY-RUN] metrics subject=$SUBJECT env=$ENV scenario=$SCENARIO rep=$REP namespace=$NS"
echo "[DRY-RUN] would compare the common expected inventory and write one schema-v2 JSON summary"
echo "[DRY-RUN] legacy CSV header: $HEADER"
echo "[DRY-RUN] nothing executed or written"
