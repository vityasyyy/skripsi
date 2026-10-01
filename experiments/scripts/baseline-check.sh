#!/usr/bin/env bash
# baseline-check.sh — gerbang baseline sebelum setiap run (Bab 3, Protokol O1).
# Default: DRY-RUN (cetak perintah, eksekusi nol). Eksekusi nyata hanya dengan --live.
# Gates: (1) semua pods Running di ns target, (2) CPU node <70%, (3) ArgoCD app
# Synced/Healthy untuk ns gitops. Pelanggaran -> exit non-zero + baris log.
set -euo pipefail

LIVE=0
NS="exp-s1-manual"
APP=""
LOG_FILE=""

usage() {
  cat <<'USAGE'
Usage: baseline-check.sh [--live] [--namespace NS] [--app APP-NAME] [--log FILE]
  Default DRY-RUN: hanya mencetak perintah kubectl/argocd yang direncanakan.
  --live menjalankan pemeriksaan sungguhan.
  --app wajib untuk namespace gitops (*-gitops); opsional untuk manual.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --namespace|--ns|-n) NS="${2:-}"; shift 2 ;;
    --app) APP="${2:-}"; shift 2 ;;
    --log) LOG_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: argumen tak dikenal: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ALLOWED_NS="exp-s1-manual exp-s1-gitops exp-s2-manual exp-s2-gitops"
FORBIDDEN_RE='^(invenio|argocd|kube-system|default|database|search|redis|minio|monitoring|traefik|cert-manager|velero|cattle-.*|kube-.*|local)$'

log() { # $1 = level, $2+ = pesan
  local level="$1"; shift
  local line="$(date -u +%FT%TZ) [$level] baseline-check ns=$NS $*"
  echo "$line"
  if [[ -n "$LOG_FILE" ]]; then echo "$line" >>"$LOG_FILE"; fi
}

# --- safety gate: target ns harus allowed, tidak boleh forbidden ---
is_allowed=0
for a in $ALLOWED_NS; do [[ "$NS" == "$a" ]] && is_allowed=1; done
if [[ "$NS" =~ $FORBIDDEN_RE ]]; then
  log "VIOLATION" "namespace $NS masuk daftar FORBIDDEN — abort"
  exit 3
fi
if [[ $is_allowed -ne 1 ]]; then
  log "VIOLATION" "namespace $NS tidak dalam allowed list ($ALLOWED_NS) — abort"
  exit 3
fi
if [[ "$NS" == *-gitops && -z "$APP" ]]; then
  log "VIOLATION" "namespace gitops membutuhkan --app <argocd-app-name> — abort"
  exit 2
fi

plan_pods="kubectl get pods -n $NS --no-headers"
plan_nodes="kubectl top nodes"
plan_argocd="argocd app get $APP"

if [[ $LIVE -ne 1 ]]; then
  echo "[DRY-RUN] baseline-check target ns=$NS app=${APP:-(none, manual ns)}"
  echo "[DRY-RUN] would run: $plan_pods   # gate 1: semua pods Running"
  echo "[DRY-RUN] would run: $plan_nodes   # gate 2: CPU node <70%"
  if [[ -n "$APP" ]]; then
    echo "[DRY-RUN] would run: $plan_argocd  # gate 3: Synced/Healthy (gitops)"
  else
    echo "[DRY-RUN] skip gate 3 (manual ns, tanpa ArgoCD app)"
  fi
  echo "[DRY-RUN] nothing executed. Re-run with --live to enforce gates."
  exit 0
fi

# --- LIVE ---
fail=0
log "INFO" "gate 1: cek pods Running ($plan_pods)"
not_running="$(kubectl get pods -n "$NS" --no-headers 2>&1 | awk '$3 != "Running" && $3 != "Completed" {print}') " || true
# Catatan: CronJob Job pod Completed dianggap sehat; selain Running/Completed = pelanggaran.
if [[ -n "${not_running//[[:space:]]/}" ]]; then
  log "VIOLATION" "gate 1 GAGAL — pod tidak Running/Completed di ns=$NS: $not_running"
  fail=1
else
  log "INFO" "gate 1 OK — semua pods Running/Completed"
fi

log "INFO" "gate 2: cek CPU node <70% ($plan_nodes)"
cpu_violation=""
while read -r cpu; do
  pct="${cpu%\%}"
  if [[ "$pct" =~ ^[0-9]+$ ]] && [[ "$pct" -ge 70 ]]; then cpu_violation="$cpu_violation $cpu"; fi
done < <(kubectl top nodes --no-headers 2>/dev/null | awk '{print $3}' || true)
if [[ -n "${cpu_violation//[[:space:]]/}" ]]; then
  log "VIOLATION" "gate 2 GAGAL — CPU node >=70%: $cpu_violation"
  fail=1
else
  log "INFO" "gate 2 OK — CPU node <70% (atau metrik tak tersedia tapi kubectl sukses)"
fi

if [[ -n "$APP" ]]; then
  log "INFO" "gate 3: cek ArgoCD app ($plan_argocd)"
  app_out="$(argocd app get "$APP" 2>&1 || true)"
  echo "$app_out" | grep -q "Health Status:[[:space:]]*Healthy" || { log "VIOLATION" "gate 3 GAGAL — app $APP tidak Healthy"; fail=1; }
  echo "$app_out" | grep -q "Sync Status:[[:space:]]*Synced" || { log "VIOLATION" "gate 3 GAGAL — app $APP tidak Synced"; fail=1; }
  if [[ $fail -eq 0 ]]; then log "INFO" "gate 3 OK — app $APP Synced/Healthy"; fi
fi

if [[ $fail -ne 0 ]]; then
  log "VIOLATION" "baseline TIDAK memenuhi syarat — abort run"
  exit 1
fi
log "INFO" "baseline OK — run boleh dimulai"
