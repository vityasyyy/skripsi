#!/usr/bin/env bash
# metrics-collect.sh — polling pasca-injeksi + hitung R1 + tulis CSV (Bab 3, Protokol O2).
# Default: DRY-RUN (cetak perintah, tulis nol baris). Tulis CSV nyata hanya dengan --live,
# atau --live-dryrun untuk menulis satu baris contoh bertanda DRYRUN (tidak menyentuh klaster).
# Gitops: poll `argocd app get <APP>` tiap 5 dtk (OutOfSync->td, Synced->t2, diff->trci).
# Manual: poll `kubectl rollout status / get` tiap 5 dtk; td/trci/t2 diisi operator+runbook,
#   script menyediakan template dan perekam timestamp.
set -euo pipefail

LIVE=0
DRYRUN_ROW=0
SUBJECT="s1"
ENV="manual"
SCENARIO="A"
REP="1"
NS="exp-s1-manual"
APP=""
T0=""
TIMEOUT="600"
OUT=""
KUBECTL_CMDS="0"
NOTES=""

usage() {
  cat <<'USAGE'
Usage: metrics-collect.sh [--live] [--live-dryrun] [--subject s1|s2] [--env manual|gitops]
       [--scenario A-G] [--rep N] [--namespace NS] [--app APP] [--t0 EPOCH]
       [--timeout SECS] [--output FILE.csv] [--kubectl-cmds N] [--notes TXT]
  Header CSV (EKSAK, jangan diubah):
  subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --live-dryrun) DRYRUN_ROW=1; shift ;;
    --subject) SUBJECT="${2:-}"; shift 2 ;;
    --env) ENV="${2:-}"; shift 2 ;;
    --scenario|-s) SCENARIO="${2:-}"; shift 2 ;;
    --rep) REP="${2:-}"; shift 2 ;;
    --namespace|--ns|-n) NS="${2:-}"; shift 2 ;;
    --app) APP="${2:-}"; shift 2 ;;
    --t0) T0="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT="${2:-}"; shift 2 ;;
    --output|-o) OUT="${2:-}"; shift 2 ;;
    --kubectl-cmds) KUBECTL_CMDS="${2:-}"; shift 2 ;;
    --notes) NOTES="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: argumen tak dikenal: $1" >&2; usage >&2; exit 2 ;;
  esac
done

HEADER="subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes"
ALLOWED_NS="exp-s1-manual exp-s1-gitops exp-s2-manual exp-s2-gitops"
FORBIDDEN_RE='^(invenio|argocd|kube-system|default|database|search|redis|minio|monitoring|traefik|cert-manager|velero|cattle-.*|kube-.*|local)$'

if [[ "$NS" =~ $FORBIDDEN_RE ]]; then echo "VIOLATION: ns $NS forbidden" >&2; exit 3; fi
is_allowed=0
for a in $ALLOWED_NS; do [[ "$NS" == "$a" ]] && is_allowed=1; done
if [[ $is_allowed -ne 1 ]]; then echo "VIOLATION: ns $NS tidak allowed" >&2; exit 3; fi
if [[ "$ENV" == "gitops" && -z "$APP" ]]; then echo "ERROR: env gitops membutuhkan --app" >&2; exit 2; fi

expected_total() { if [[ "$SUBJECT" == "s1" ]]; then echo 5; else echo 7; fi; }

# R1: % sumber daya cocok desired state (Bab 3: Healthy/Synced / total expected).
# Gitops: dari `argocd app get`; manual: dari kubectl get per-kind.
r1_gitops() { # $1=app -> skor 0-100 atau kosong bila gagal
  local out total healthy
  out="$(argocd app get "$1" 2>/dev/null || true)"
  total="$(expected_total)"
  if echo "$out" | grep -q "Sync Status:[[:space:]]*Synced" && \
     echo "$out" | grep -q "Health Status:[[:space:]]*Healthy"; then echo 100; else echo 0; fi
}
r1_manual() { # $1=ns -> skor 0-100 berbasis hitung resource Ready
  local ns="$1" total ok
  total="$(expected_total)"
  ok=0
  [[ "$(kubectl get deployment/exp-web -n "$ns" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo X)" == "3" ]] && ok=$((ok+1))
  kubectl get svc/exp-web -n "$ns" >/dev/null 2>&1 && ok=$((ok+1))
  [[ "$(kubectl get cm/exp-web-config -n "$ns" -o jsonpath='{.data.LOG_LEVEL}' 2>/dev/null || echo X)" == "info" ]] && ok=$((ok+1))
  [[ "$(kubectl get secret/exp-web-secret -n "$ns" -o jsonpath='{.data.password}' 2>/dev/null || echo X)" == "ZXhwLXNlY3JldC0xMjM=" ]] && ok=$((ok+1))
  kubectl get cronjob/exp-web-tick -n "$ns" >/dev/null 2>&1 && ok=$((ok+1))
  if [[ "$SUBJECT" == "s2" ]]; then
    [[ "$(kubectl get statefulset/exp-store -n "$ns" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo X)" == "1" ]] && ok=$((ok+1))
    kubectl get pvc/exp-store-data -n "$ns" >/dev/null 2>&1 && ok=$((ok+1))
  fi
  echo $(( ok * 100 / total ))
}

if [[ $LIVE -ne 1 && $DRYRUN_ROW -ne 1 ]]; then
  echo "[DRY-RUN] metrics-collect subject=$SUBJECT env=$ENV skenario=$SCENARIO rep=$REP ns=$NS"
  if [[ "$ENV" == "gitops" ]]; then
    echo "[DRY-RUN] would run: argocd app get $APP                    # poll tiap 5s: Synced->OutOfSync (td) ->Synced (t2)"
    echo "[DRY-RUN] would run: argocd app diff $APP                   # diff tersedia -> trci"
  else
    echo "[DRY-RUN] would run: kubectl rollout status deployment/exp-web -n $NS     # poll tiap 5s"
    echo "[DRY-RUN] would run: kubectl get all -n $NS                               # snapshot R1 t0/t1/t2"
    echo "[DRY-RUN] td/trci/t2 manual diisi dari timestamp recovery-runbook.sh"
  fi
  echo "[DRY-RUN] would compute R1 (total_expected=$(expected_total)) at t0/t1/t2"
  echo "[DRY-RUN] would append CSV header+row to: ${OUT:-(stdout, --output FILE untuk tulis)}"
  echo "[DRY-RUN] header: $HEADER"
  echo "[DRY-RUN] nothing executed, nothing written. Re-run with --live (atau --live-dryrun untuk contoh baris)."
  exit 0
fi

if [[ -z "$T0" ]]; then T0="$(date +%s)"; fi
if [[ -z "$OUT" && $DRYRUN_ROW -ne 1 ]]; then echo "ERROR: --output FILE.csv wajib untuk --live" >&2; exit 2; fi

if [[ $DRYRUN_ROW -eq 1 ]]; then
  # Baris contoh tanpa menyentuh klaster; t* diisi placeholder epoch T0.
  row="$SUBJECT,$ENV,$SCENARIO,$REP,$T0,$T0,$T0,$T0,100,0,100,0,DRYRUN-sample-tidak-menyentuh-klaster"
  if [[ -n "$OUT" ]]; then
    [[ -f "$OUT" ]] || echo "$HEADER" >"$OUT"
    echo "$row" >>"$OUT"
    echo "[live-dryrun] wrote sample row to $OUT"
  else
    echo "$HEADER"; echo "$row"
  fi
  exit 0
fi

# --- LIVE ---
td=""; trci=""; t2=""
r1_t0=""; r1_t1=""; r1_t2=""
if [[ "$ENV" == "gitops" ]]; then r1_t0="$(r1_gitops "$APP")"; else r1_t0="$(r1_manual "$NS")"; fi
elapsed=0
while [[ $elapsed -lt $TIMEOUT ]]; do
  if [[ "$ENV" == "gitops" ]]; then
    out="$(argocd app get "$APP" 2>/dev/null || true)"
    if [[ -z "$td" ]] && echo "$out" | grep -q "Sync Status:[[:space:]]*OutOfSync"; then
      td="$(date +%s)"
      if echo "$out" | grep -q "Health Status"; then trci="$(date +%s)"; fi
      if [[ "$ENV" == "gitops" ]]; then r1_t1="$(r1_gitops "$APP")"; fi
    fi
    if [[ -n "$td" && -z "$t2" ]] && echo "$out" | grep -q "Sync Status:[[:space:]]*Synced" \
       && echo "$out" | grep -q "Health Status:[[:space:]]*Healthy"; then
      t2="$(date +%s)"; break
    fi
  else
    # Manual: deteksi via status rollout/get; pemulihan selesai ditandai operator
    # menekan ENTER setelah runbook selesai (timestamp otomatis), atau timeout.
    if [[ -z "$td" ]]; then
      if ! kubectl rollout status deployment/exp-web -n "$NS" --timeout=5s >/dev/null 2>&1; then
        td="$(date +%s)"; trci="$td"; r1_t1="$(r1_manual "$NS")"
        echo "[manual] drift terdeteksi td=$td — jalankan recovery-runbook.sh lalu tekan ENTER" >&2
      fi
    fi
    if [[ -n "$td" ]]; then
      read -r -t 5 _enter 2>/dev/null && { t2="$(date +%s)"; break; } || true
    fi
  fi
  sleep 5; elapsed=$((elapsed+5))
done
[[ -z "$td" ]] && td="$T0"
[[ -z "$trci" ]] && trci="$td"
[[ -z "$t2" ]] && t2="$(date +%s)"
if [[ "$ENV" == "gitops" ]]; then r1_t2="$(r1_gitops "$APP")"; else r1_t2="$(r1_manual "$NS")"; fi
[[ -z "$r1_t1" ]] && { if [[ "$ENV" == "gitops" ]]; then r1_t1="$(r1_gitops "$APP")"; else r1_t1="$(r1_manual "$NS")"; fi; }
row="$SUBJECT,$ENV,$SCENARIO,$REP,$T0,$td,$trci,$t2,$r1_t0,$r1_t1,$r1_t2,$KUBECTL_CMDS,$NOTES"
[[ -f "$OUT" ]] || echo "$HEADER" >"$OUT"
echo "$row" >>"$OUT"
echo "[live] wrote: $row -> $OUT"
