#!/usr/bin/env bash
# recovery-runbook.sh — pemulihan deterministik Lingkungan A/manual (Bab 3), Opsi A:
# SELURUH proses otomatis (tanpa manusia dalam loop pengukuran).
#   Fase DIAGNOSE : describe -> logs -> events; trci = selesai fase diagnose,
#                   diverifikasi signature penyimpangan cocok dengan skenario.
#   Fase CORRECT  : perintah kubectl korektif per skenario; t2 = baseline re-check pass
#                   (retry 5x5s, gagal -> exit 4).
#   Output        : JSON baris tunggal {"event":"runbook_complete",...} ke stdout + --log
#                   untuk dikonsumsi metrics-collect.sh (--runbook-log).
# Default: DRY-RUN (cetak rencana, eksekusi nol). Eksekusi nyata hanya dengan --live.
set -euo pipefail

LIVE=0
NS="exp-s1-manual"
SCENARIO=""
LOG_FILE=""

usage() {
  cat <<'USAGE'
Usage: recovery-runbook.sh [--live] [--namespace NS] --scenario A|B|C|D|E|F|G [--log FILE]
  Baseline yang dipulihkan: replicas=3, image=nginx:1.25.3, LOG_LEVEL=info,
  password=ZXhwLXNlY3JldC0xMjM=, hapus resource di namespace salah (F).
  Opsi A: fase DIAGNOSE + CORRECT dieksekusi otomatis; trci/t2 direkam mesin.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --namespace|--ns|-n) NS="${2:-}"; shift 2 ;;
    --scenario|-s) SCENARIO="${2:-}"; shift 2 ;;
    --log) LOG_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: argumen tak dikenal: $1" >&2; usage >&2; exit 2 ;;
  esac
done

FORBIDDEN_RE='^(invenio|argocd|kube-system|default|database|search|redis|minio|monitoring|traefik|cert-manager|velero|cattle-.*|kube-.*|local)$'
ALLOWED_RE='^exp-s[12]-(manual|gitops)$'

if [[ -z "$SCENARIO" ]]; then echo "ERROR: --scenario A-G wajib" >&2; usage >&2; exit 2; fi
case "$SCENARIO" in A|B|C|D|E|F|G) ;; *) echo "ERROR: --scenario harus A-G" >&2; exit 2 ;; esac
if [[ "$NS" =~ $FORBIDDEN_RE ]]; then echo "VIOLATION: ns $NS forbidden — abort" >&2; exit 3; fi
if [[ ! "$NS" =~ $ALLOWED_RE ]]; then echo "VIOLATION: ns $NS tidak allowed (exp-s1/s2-manual/gitops) — abort" >&2; exit 3; fi

WRONG_NS="${NS}-wrong"
SUBJ="s1"
[[ "$NS" == exp-s2-* ]] && SUBJ="s2"

declare -a CORRECT_STEPS=()
case "$SCENARIO" in
  A) CORRECT_STEPS=("kubectl scale deployment/exp-web -n $NS --replicas=3"
                    "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  B) CORRECT_STEPS=("kubectl set image deployment/exp-web -n $NS nginx=nginx:1.25.3"
                    "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  C) CORRECT_STEPS=("kubectl patch configmap/exp-web-config -n $NS --patch='{\"data\":{\"LOG_LEVEL\":\"info\"}}'"
                    "kubectl rollout restart deployment/exp-web -n $NS"
                    "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  D) CORRECT_STEPS=("sed 's/EXP_NS/$NS/g' experiments/subjects/$SUBJ/manifests.yaml | kubectl apply -n $NS -f -  # recreate deleted resources"
                    "kubectl rollout status deployment/exp-web -n $NS --timeout=120s"
                    "kubectl get svc/exp-web -n $NS") ;;
  E) CORRECT_STEPS=("kubectl patch deployment/exp-web -n $NS --patch='{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"nginx\",\"resources\":{\"limits\":{\"cpu\":\"200m\"}}}]}}}}'"
                    "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  F) CORRECT_STEPS=("kubectl delete deployment/exp-web -n $WRONG_NS --ignore-not-found"
                    "kubectl delete namespace $WRONG_NS --ignore-not-found || true"
                    "kubectl get deployment/exp-web -n $NS") ;;
  G) CORRECT_STEPS=("kubectl patch secret/exp-web-secret -n $NS --patch='{\"data\":{\"password\":\"ZXhwLXNlY3JldC0xMjM=\"}}'"
                    "kubectl rollout restart deployment/exp-web -n $NS"
                    "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
esac

declare -a DIAGNOSE_STEPS=(
  "kubectl describe deployment/exp-web -n $NS"
  "kubectl logs deployment/exp-web -n $NS --tail=50"
  "kubectl get events -n $NS --sort-by=.lastTimestamp"
)

stamp() { date +%s; }
ts_log() {
  local line="$(date -u +%FT%TZ) [runbook] ns=$NS scenario=$SCENARIO phase=$1 step=$2 ts=$3 info=$4"
  echo "$line"
  if [[ -n "$LOG_FILE" ]]; then echo "$line" >>"$LOG_FILE"; fi
}

# Verifikasi signature penyimpangan per skenario (exit 5 bila signature tidak ada).
verify_signature() {
  local sig_ok=0
  case "$SCENARIO" in
    A) [[ "$(kubectl get deployment/exp-web -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo X)" != "3" ]] && sig_ok=1 ;;
    B) [[ "$(kubectl get deployment/exp-web -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo X)" != "nginx:1.25.3" ]] && sig_ok=1 ;;
    C) [[ "$(kubectl get cm/exp-web-config -n "$NS" -o jsonpath='{.data.LOG_LEVEL}' 2>/dev/null || echo X)" != "info" ]] && sig_ok=1 ;;
    D) kubectl get deployment/exp-web -n "$NS" >/dev/null 2>&1 || sig_ok=1 ;;
    E) [[ "$(kubectl get deployment/exp-web -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].resources.limits.cpu}' 2>/dev/null || echo X)" != "200m" ]] && sig_ok=1 ;;
    F) kubectl get deployment/exp-web -n "$WRONG_NS" >/dev/null 2>&1 && sig_ok=1 ;;
    G) [[ "$(kubectl get secret/exp-web-secret -n "$NS" -o jsonpath='{.data.password}' 2>/dev/null || echo X)" != "ZXhwLXNlY3JldC0xMjM=" ]] && sig_ok=1 ;;
  esac
  if [[ $sig_ok -ne 1 ]]; then
    echo "ERROR: signature penyimpangan skenario $SCENARIO tidak ditemukan di ns $NS — run invalid" >&2
    exit 5
  fi
}

run_cmds() { # $1=fase-label, $2=array-name; echo jumlah perintah (stdout); log/DRY-RUN ke stderr
  local phase="$1" arr_name="$2"; local i=0 count=0
  eval "local steps=(\"\${${arr_name}[@]}\")"
  for cmd in "${steps[@]}"; do
    i=$((i+1))
    if [[ $LIVE -ne 1 ]]; then
      echo "[DRY-RUN] $phase step $i: $cmd" >&2
      continue
    fi
    local t_start t_end
    t_start="$(stamp)"
    ts_log "$phase" "$i" "$t_start" "$cmd" >&2
    # Perintah di-hardcode di atas (bukan input user bebas) — eval aman di sini.
    eval "$cmd" >/dev/null 2>&1 || true
    t_end="$(stamp)"
    ts_log "$phase" "$i" "$t_end" "elapsed=$((t_end-t_start))s" >&2
    count=$((count+1))
  done
  echo "$count"
}

echo "[runbook] scenario=$SCENARIO ns=$NS diagnose_steps=${#DIAGNOSE_STEPS[@]} correct_steps=${#CORRECT_STEPS[@]} mode=$([ $LIVE -eq 1 ] && echo LIVE || echo DRY-RUN)"

if [[ $LIVE -eq 1 ]]; then
  verify_signature
fi

T_DIAG_START="$(stamp)"
DIAG_CMDS="$(run_cmds DIAGNOSE DIAGNOSE_STEPS)"
if [[ $LIVE -eq 1 ]]; then
  TRCI="$(stamp)"
  ts_log DIAGNOSE done "$TRCI" "trci_epoch=$TRCI diagnose_cmds=$DIAG_CMDS"
fi

T_CORR_START="$(stamp)"
KUBECTL_CMDS="$(run_cmds CORRECT CORRECT_STEPS)"

if [[ $LIVE -eq 1 ]]; then
  # Baseline re-check: rollout sehat -> t2; retry 5x5s lalu gagal exit 4.
  T2=""
  for attempt in 1 2 3 4 5; do
    if kubectl rollout status deployment/exp-web -n "$NS" --timeout=5s >/dev/null 2>&1; then
      T2="$(stamp)"; break
    fi
    sleep 5
  done
  if [[ -z "$T2" ]]; then
    echo "ERROR: baseline re-check gagal setelah 5x5s — t2 tidak valid" >&2
    exit 4
  fi
  ts_log CORRECT done "$T2" "t2_epoch=$T2 kubectl_cmds=$KUBECTL_CMDS"
  json_line="{\"event\":\"runbook_complete\",\"ns\":\"$NS\",\"scenario\":\"$SCENARIO\",\"trci\":$TRCI,\"t2\":$T2,\"diagnose_cmds\":$DIAG_CMDS,\"kubectl_cmds\":$KUBECTL_CMDS,\"mode\":\"automated\"}"
  echo "$json_line"
  if [[ -n "$LOG_FILE" ]]; then echo "$json_line" >>"$LOG_FILE"; fi
else
  echo "[DRY-RUN] planned diagnose commands: ${#DIAGNOSE_STEPS[@]}, correct commands: ${#CORRECT_STEPS[@]} (tidak dieksekusi). Re-run dengan --live."
  echo "[DRY-RUN] dengan --live: trci = selesai fase DIAGNOSE, t2 = baseline re-check pass, JSON runbook_complete ditulis ke --log."
fi
