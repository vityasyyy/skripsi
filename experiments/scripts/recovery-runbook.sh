#!/usr/bin/env bash
# recovery-runbook.sh — prosedur pemulihan deterministik Lingkungan A/manual (Bab 3).
# Default: DRY-RUN (cetak langkah, eksekusi nol, hitung rencana perintah).
# Dengan --live: eksekusi langkah berurutan, timestamp tiap step, hitung perintah.
set -euo pipefail

LIVE=0
NS="exp-s1-manual"
SCENARIO=""
LOG_FILE=""
COUNT=0

usage() {
  cat <<'USAGE'
Usage: recovery-runbook.sh [--live] [--namespace NS] --scenario A|B|C|D|E|F|G [--log FILE]
  Baseline yang dipulihkan: replicas=3, image=nginx:1.25.3, LOG_LEVEL=info,
  password=ZXhwLXNlY3JldC0xMjM=, hapus resource di namespace salah (F).
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
# Subjek diturunkan dari namespace: exp-s1-* -> s1, exp-s2-* -> s2.
SUBJ="s1"
[[ "$NS" == exp-s2-* ]] && SUBJ="s2"
declare -a STEPS=()
case "$SCENARIO" in
  A) STEPS=("kubectl scale deployment/exp-web -n $NS --replicas=3"
            "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  B) STEPS=("kubectl set image deployment/exp-web -n $NS nginx=nginx:1.25.3"
            "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  C) STEPS=("kubectl patch configmap/exp-web-config -n $NS --patch='{\"data\":{\"LOG_LEVEL\":\"info\"}}'"
            "kubectl rollout restart deployment/exp-web -n $NS"
            "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  D) STEPS=("sed 's/EXP_NS/$NS/g' experiments/subjects/$SUBJ/manifests.yaml | kubectl apply -n $NS -f -  # recreate deleted resources"
            "kubectl rollout status deployment/exp-web -n $NS --timeout=120s"
            "kubectl get svc/exp-web -n $NS") ;;
  E) STEPS=("kubectl patch deployment/exp-web -n $NS --patch='{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"nginx\",\"resources\":{\"limits\":{\"cpu\":\"200m\"}}}]}}}}'"
            "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
  F) STEPS=("kubectl delete deployment/exp-web -n $WRONG_NS --ignore-not-found"
            "kubectl delete namespace $WRONG_NS --ignore-not-found || true"
            "kubectl get deployment/exp-web -n $NS") ;;
  G) STEPS=("kubectl patch secret/exp-web-secret -n $NS --patch='{\"data\":{\"password\":\"ZXhwLXNlY3JldC0xMjM=\"}}'"
            "kubectl rollout restart deployment/exp-web -n $NS"
            "kubectl rollout status deployment/exp-web -n $NS --timeout=120s") ;;
esac

stamp() { date +%s; }
ts_log() {
  local line="$(date -u +%FT%TZ) [runbook] ns=$NS scenario=$SCENARIO step=$1 ts=$2 cmd=$3"
  echo "$line"
  if [[ -n "$LOG_FILE" ]]; then echo "$line" >>"$LOG_FILE"; fi
}

echo "[runbook] scenario=$SCENARIO ns=$NS steps=${#STEPS[@]} mode=$([ $LIVE -eq 1 ] && echo LIVE || echo DRY-RUN)"
i=0
for cmd in "${STEPS[@]}"; do
  i=$((i+1))
  if [[ $LIVE -ne 1 ]]; then
    echo "[DRY-RUN] step $i/${#STEPS[@]} would run: $cmd"
    continue
  fi
  t_start="$(stamp)"
  ts_log "$i-start" "$t_start" "$cmd"
  # STEPS di-hardcode di atas (bukan input user bebas) — eval aman di sini.
  eval "$cmd"
  t_end="$(stamp)"
  ts_log "$i-end" "$t_end" "elapsed=$((t_end-t_start))s"
  COUNT=$((COUNT+1))
done

if [[ $LIVE -ne 1 ]]; then
  echo "[DRY-RUN] planned kubectl commands: ${#STEPS[@]} (tidak dieksekusi). Re-run dengan --live."
else
  echo "[live] executed kubectl commands: $COUNT"
fi
