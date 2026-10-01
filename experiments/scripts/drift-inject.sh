#!/usr/bin/env bash
# drift-inject.sh — injeksi penyimpangan terkontrol skenario A-G (Bab 3).
# Default: DRY-RUN (cetak perintah, eksekusi nol). Eksekusi nyata hanya dengan --live.
# Urutan acak via shuf (default) untuk hindari order effect; --order sequential untuk debug.
# Mencatat t0 epoch (detik) per skenario ke stdout/log.
set -euo pipefail

LIVE=0
NS="exp-s1-manual"
SCENARIO="all"
ORDER="random"
SEED_NOTE=""
LOG_FILE=""

usage() {
  cat <<'USAGE'
Usage: drift-inject.sh [--live] [--namespace NS] [--scenario A|B|C|D|E|F|G|all]
                       [--order random|sequential] [--log FILE]
  Skenario (Bab 3):
    A replica scale   : kubectl scale deployment/exp-web --replicas=5
    B image edit      : kubectl set image deployment/exp-web nginx=nginx:1.26-alpine
    C configmap edit  : kubectl patch configmap/exp-web-config (LOG_LEVEL=debug)
    D resource delete : kubectl delete deployment/exp-web
    E manual patch    : kubectl patch deployment/exp-web (resource limits cpu=500m)
    F cross-namespace : kubectl apply copy deployment ke <NS>-wrong (quarantine)
    G secret patch    : kubectl patch secret/exp-web-secret (password=ZHJpZnQtZ2l0b3Bz)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live) LIVE=1; shift ;;
    --namespace|--ns|-n) NS="${2:-}"; shift 2 ;;
    --scenario|-s) SCENARIO="${2:-}"; shift 2 ;;
    --order) ORDER="${2:-}"; shift 2 ;;
    --log) LOG_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: argumen tak dikenal: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ALLOWED_NS="exp-s1-manual exp-s1-gitops exp-s2-manual exp-s2-gitops"
FORBIDDEN_RE='^(invenio|argocd|kube-system|default|database|search|redis|minio|monitoring|traefik|cert-manager|velero|cattle-.*|kube-.*|local)$'

log() {
  local line="$(date -u +%FT%TZ) [drift-inject] ns=$NS scenario=$1 t0=$2 $3"
  echo "$line"
  if [[ -n "$LOG_FILE" ]]; then echo "$line" >>"$LOG_FILE"; fi
}

if [[ "$NS" =~ $FORBIDDEN_RE ]]; then
  echo "VIOLATION: namespace $NS forbidden — abort" >&2; exit 3
fi
is_allowed=0
for a in $ALLOWED_NS; do [[ "$NS" == "$a" ]] && is_allowed=1; done
if [[ $is_allowed -ne 1 ]]; then
  echo "VIOLATION: namespace $NS tidak allowed ($ALLOWED_NS) — abort" >&2; exit 3
fi
case "$SCENARIO" in A|B|C|D|E|F|G|all) ;; *) echo "ERROR: --scenario harus A-G/all" >&2; exit 2 ;; esac
case "$ORDER" in random|sequential) ;; *) echo "ERROR: --order random|sequential" >&2; exit 2 ;; esac

WRONG_NS="${NS}-wrong"
# Skenario F memakai quarantine namespace turunan (<NS>-wrong), BUKAN namespace
# sistem. Pola ini tidak masuk FORBIDDEN; cleanup di recovery-runbook.sh (skenario F).

inject_cmd() { # $1 = huruf skenario -> echo perintah kubectl
  case "$1" in
    A) echo "kubectl scale deployment/exp-web -n $NS --replicas=5" ;;
    B) echo "kubectl set image deployment/exp-web -n $NS nginx=nginx:1.26-alpine" ;;
    C) echo "kubectl patch configmap/exp-web-config -n $NS --patch='{\"data\":{\"LOG_LEVEL\":\"debug\"}}'" ;;
    D) echo "kubectl delete deployment/exp-web -n $NS" ;;
    E) echo "kubectl patch deployment/exp-web -n $NS --patch='{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"nginx\",\"resources\":{\"limits\":{\"cpu\":\"500m\"}}}]}}}}'" ;;
    F) echo "kubectl get deployment/exp-web -n $NS -o yaml | sed 's/namespace: $NS/namespace: $WRONG_NS/' | kubectl apply -n $WRONG_NS -f -" ;;
    G) echo "kubectl patch secret/exp-web-secret -n $NS --patch='{\"data\":{\"password\":\"ZHJpZnQtZ2l0b3Bz\"}}'" ;;
  esac
}

if [[ "$SCENARIO" == "all" ]]; then LIST="A B C D E F G"; else LIST="$SCENARIO"; fi
if [[ "$ORDER" == "random" && "$SCENARIO" == "all" ]]; then
  if command -v shuf >/dev/null 2>&1; then
    # shellcheck disable=SC2206
    LIST="$(echo $LIST | tr ' ' '\n' | shuf | tr '\n' ' ')"
    SEED_NOTE="(urutan acak via shuf)"
  else
    # Fallback portabel (macOS tanpa shuf): Fisher-Yates murni-bash via $RANDOM.
    arr=($LIST); n=${#arr[@]}
    for ((k=n-1; k>0; k--)); do
      j=$((RANDOM % (k+1))); tmp="${arr[k]}"; arr[k]="${arr[j]}"; arr[j]="$tmp"
    done
    LIST="${arr[*]}"
    SEED_NOTE="(urutan acak via bash-RANDOM fallback, shuf tak tersedia)"
  fi
else
  SEED_NOTE="(urutan sequential)"
fi

echo "[drift-inject] target ns=$NS skenario=[$LIST] $SEED_NOTE mode=$([ $LIVE -eq 1 ] && echo LIVE || echo DRY-RUN)"

for s in $LIST; do
  cmd="$(inject_cmd "$s")"
  if [[ $LIVE -ne 1 ]]; then
    echo "[DRY-RUN] scenario $s t0=<epoch-saat-live> would run: $cmd"
    continue
  fi
  t0="$(date +%s)"
  log "$s" "$t0" "EXEC: $cmd"
  # shellcheck disable=SC2086
  if [[ "$s" == "F" ]]; then
    kubectl create namespace "$WRONG_NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    eval "$cmd"
  else
    eval "$cmd"
  fi
  # verifikasi pasca-injeksi (read-only, aman)
  case "$s" in
    A) kubectl get deployment/exp-web -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null; echo ;;
    D) kubectl get deployment/exp-web -n "$NS" 2>&1 | head -1 ;;
    F) kubectl get deployment/exp-web -n "$WRONG_NS" 2>&1 | head -1 ;;
  esac
  log "$s" "$t0" "DONE t0=$t0"
done
