# WORKER-REPORT — agent/exp-harness (Bab-3 experiment harness)

## 0. STEP 0 — konteks klaster
- Perintah: `export KUBECONFIG="$HOME/.kube/config" && kubectl config current-context`
- Output: `btd` (eksak, sesuai syarat). Lanjut. Tidak ada `--live` dijalankan di wave ini.

## 1. What changed (hanya path dalam scope)
- `experiments/subjects/s1/manifests.yaml` (baru): S1 exp-s1, 5 resources, placeholder `EXP_NS`.
  Deployment `exp-web` (nginx:1.25.3, 3 replicas) + Service `exp-web` + ConfigMap
  `exp-web-config` (LOG_LEVEL=info) + Secret `exp-web-secret` + CronJob `exp-web-tick`.
- `experiments/subjects/s2/manifests.yaml` (baru): S2 = isi S1 (label subject:s2) +
  StatefulSet `exp-store` (1 replica, nginx:1.25.3, mount PVC) + PVC `exp-store-data` (1Gi).
  Total 7 resources, placeholder `EXP_NS`.
- `experiments/subjects/README.md` (baru): tabel inventaris per subjek + cara dry-run via sed.
- `experiments/scripts/baseline-check.sh` (baru, +x): DRY-RUN default, `--live` untuk eksekusi.
  Gates: pods Running, CPU node <70%, ArgoCD Synced/Healthy (wajib `--app` untuk ns gitops).
  Pelanggaran -> exit non-zero + baris log `VIOLATION`.
- `experiments/scripts/drift-inject.sh` (baru, +x): skenario A-G Bab 3, acak via `shuf`
  (fallback bash-RANDOM portabel bila `shuf` tak ada, e.g. macOS), catat t0 epoch, eksekusi hanya `--live`.
- `experiments/scripts/metrics-collect.sh` (baru, +x): poll `argocd app get` tiap 5 dtk (gitops) /
  kubectl polling (manual), catat td/trci/t2, hitung R1 t0/t1/t2, tulis CSV header eksak.
  DRY-RUN default; `--live-dryrun` menulis satu baris contoh tanpa menyentuh klaster.
- `experiments/scripts/recovery-runbook.sh` (baru, +x): langkah deterministik per skenario
  untuk Lingkungan A, timestamp tiap step, hitung perintah. DRY-RUN default.
- `experiments/runs/sample-dryrun.csv` (baru): header eksak + 1 baris DRYRUN.
- Safety di semua skrip: denylist `invenio|argocd|kube-system|default|database|search|redis|minio|monitoring|traefik|cert-manager|velero|cattle-*|kube-*|local` -> abort exit 3;
  allowlist `exp-s1-manual exp-s1-gitops exp-s2-manual exp-s2-gitops`.
  Tidak disentuh: `content/ docs/ presentation/` atau worktree lain.

File list:
```
experiments/subjects/s1/manifests.yaml
experiments/subjects/s2/manifests.yaml
experiments/subjects/README.md
experiments/scripts/baseline-check.sh
experiments/scripts/drift-inject.sh
experiments/scripts/metrics-collect.sh
experiments/scripts/recovery-runbook.sh
experiments/runs/sample-dryrun.csv
WORKER-REPORT.md
```

## 2. Verification (perintah + output, tanpa --live ke klaster tulis)
1. `bash -n` keempat skrip:
```
baseline-check.sh: syntax OK
drift-inject.sh: syntax OK
metrics-collect.sh: syntax OK
recovery-runbook.sh: syntax OK
```
2. Dry-run apply S1:
```
sed 's/EXP_NS/exp-s1-manual/g' experiments/subjects/s1/manifests.yaml | kubectl apply --dry-run=client -f -
configmap/exp-web-config created (dry run)
secret/exp-web-secret created (dry run)
deployment.apps/exp-web created (dry run)
service/exp-web created (dry run)
cronjob.batch/exp-web-tick created (dry run)
```
   Dry-run apply S2:
```
... exp-s2-manual ...
configmap/exp-web-config created (dry run)
secret/exp-web-secret created (dry run)
deployment.apps/exp-web created (dry run)
service/exp-web created (dry run)
cronjob.batch/exp-web-tick created (dry run)
persistentvolumeclaim/exp-store-data created (dry run)
statefulset.apps/exp-store created (dry run)
```
   Keduanya exit 0.
3. CSV header:
```
subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes
```
   `head -1 experiments/runs/sample-dryrun.csv` cocok eksak.
4. Read-only ArgoCD (satu-satunya perintah baca ke ns argocd, sesuai acceptance):
```
kubectl -n argocd get cm argocd-cm -o yaml
...
  timeout.reconciliation: 30s
...
```
   Full output tercatat di seksi 3.
5. DRY-RUN tiap skrip (ringkas, exit 0):
   - `baseline-check.sh --namespace exp-s1-manual` -> print 2 gate, skip gate 3.
   - `baseline-check.sh --namespace exp-s1-gitops --app exp-s1-gitops` -> print 3 gate.
   - `drift-inject.sh --namespace exp-s1-manual --scenario all --order sequential` -> A-G berurutan.
   - `drift-inject.sh --order random` -> acak (fallback bash-RANDOM di macOS, lihat seksi 5 Q1).
   - `metrics-collect.sh --env gitops ...` -> rencana `argocd app get/diff` tiap 5s, total_expected=5.
   - `metrics-collect.sh --env manual ... s2` -> rencana rollout/get, total_expected=7.
   - `recovery-runbook.sh --scenario A` -> 2 langkah; `--scenario F` -> cleanup `<NS>-wrong`.
6. Safety gate negatif (exit 3, tidak menyentuh klaster):
```
baseline-check.sh --namespace invenio -> VIOLATION ... abort (exit=3)
drift-inject.sh --namespace default -> VIOLATION (exit=3)
recovery-runbook.sh --namespace kube-system -> VIOLATION (exit=3)
metrics-collect.sh --namespace default -> VIOLATION (exit=3)
```

## 3. ArgoCD sync-interval finding (thesis 60s vs aktual)
- Thesis Bab 3 berasumsi: sync interval 60 dtk (bukan default 180 dtk), self-heal+prune aktif.
- Aktual dari `kubectl -n argocd get cm argocd-cm -o yaml` (2026-10-01):
```yaml
apiVersion: v1
data:
  account.anonymous.enabled: "false"
  accounts.github-actions: apiKey
  server.disable.auth: "false"
  statusbadge.enabled: "true"
  timeout.reconciliation: 30s
  users.anonymous.enabled: "false"
kind: ConfigMap
metadata:
  creationTimestamp: "2026-04-14T04:58:33Z"
  labels:
    app.kubernetes.io/instance: argocd-self
    app.kubernetes.io/name: argocd
    app.kubernetes.io/part-of: argocd
  name: argocd-cm
  namespace: argocd
  resourceVersion: "119202285"
  uid: 4269247b-2617-4e61-895f-32e10d34b2df
```
- Tidak ada kunci `timeout.hard.reconciliation` / `application.sync` kustom di `argocd-cm`;
  yang tercatat hanya `timeout.reconciliation: 30s`.
- Artinya asumsi naskah (60 dtk) ≠ konfigurasi klaster saat ini (30 dtk).
  Dampak: waktu deteksi R2 Lingkungan B di thesis akan over-estimasi ~2x bila memakai 60 dtk.
  Rekomendasi: sebelum wave live, selaraskan salah satu — ubah `argocd-cm` ke 60s sesuai Bab 3,
  atau revisi Bab 3 ke 30s + catat sebagai kontrol variabel. Diputuskan operator (lihat Q2).

## 4. What remains (wave berikutnya, bukan wave ini)
- Buat namespace `exp-s1-manual exp-s1-gitops exp-s2-manual exp-s2-gitops` + ArgoCD Applications
  (nama yang dipakai skrip: `<ns>` sebagai default `--app`, e.g. `exp-s1-gitops`).
- Wave `--live`: `baseline-check.sh --live` -> `drift-inject.sh --live` ->
  `metrics-collect.sh --live` + `recovery-runbook.sh --live` (manual), kumpulkan n=5 (R1)/n=10 (R2).
- NASA-TLX + survei Likert pasca-skenario (Bab 3 § mitigasi bias operator) belum diotomasi —
  butuh template kuesioner.
- Snapshot `kubectl get all` + Git history/ArgoCD notifications untuk R3.

## 5. Escalation — pertanyaan yang dihentikan, tidak ditebak
- Q1 (shuf di macOS): brief mewajibkan "random order via shuf", tetapi `shuf` tidak ada di
  host darwin ini (`shuf: command not found`). Implementasi: pakai `shuf` bila tersedia,
  fallback Fisher-Yates bash-`$RANDOM` bila tidak (tercatat di output sebagai
  "bash-RANDOM fallback"). Mohon konfirmasi: (a) terima fallback, atau (b) wajib install
  coreutils/shuf di runner eksperimen Linux nanti.
- Q2 (sync interval): thesis 60s vs aktual 30s (seksi 3). Pilih: (a) set `argocd-cm`
  `timeout.reconciliation: 60s` sebelum live, atau (b) revisi Bab 3 ke 30s.
- Q3 (Skenario F vs allowlist): brief membatasi namespace ke 4 `exp-*`, tetapi skenario F
  adalah "apply ke namespace yang salah". Implementasi saat ini memakai quarantine
  `<NS>-wrong` (e.g. `exp-s1-manual-wrong`), bukan namespace sistem, dengan cleanup di
  runbook F. Mohon konfirmasi: (a) terima pola quarantine, (b) atau F harus memakai salah
  satu dari 4 ns allowed sebagai "wrong" (akan mencemari env lain — tidak disarankan).
- Q4 (nama ArgoCD Application): skrip default `--app <ns>` (e.g. `exp-s1-gitops`).
  Jika nama Application GitOps wave memakai konvensi lain, kabari agar default diperbarui.
- Q5 (trci manual): `metrics-collect.sh` manual menandai td saat rollout gagal dan menunggu
  operator menekan ENTER pasca-runbook sebagai t2; trci default = td. Jika operator
  menghendaki trci manual diukur dari langkah `kubectl describe/logs/events` terpisah,
  perlu spesifikasi urutan describe yang mengikat.

## 6. PATCH NOTE (2026-10-01) — fix(experiments): require shuf for randomized scenario order
- Operator decision Q1: `shuf` MANDATORY, tanpa silent fallback. `drift-inject.sh` kini
  exit 127 + pesan INSTALL bila `--order random` tanpa `shuf` di PATH; jalur fallback
  bash-RANDOM Fisher-Yates dihapus. `--order sequential` tetap jalan tanpa shuf.
- `experiments/subjects/README.md` + Prerequisites: shuf (coreutils), kubectl>=1.29,
  argocd CLI v2.12+, bash>=4.
- Verifikasi patch (tanpa cluster writes):
  - `bash -n experiments/scripts/drift-inject.sh` -> OK.
  - Native `--order random` di host darwin ini -> gagal sesuai desain (shuf belum
    terinstal): `ERROR: 'shuf' (coreutils) tidak ditemukan ... INSTALL coreutils
    (macOS: brew install coreutils + PATH with gnubin shuf ...; Linux: apt-get
    install coreutils).`, exit=127. Artinya runner eksperimen wajib
    `brew install coreutils` + gnubin PATH (atau Linux coreutils) sebelum wave live.
  - PATH-shadow negatif: `mkdir -p /tmp/noshuf && PATH=/tmp/noshuf:/usr/bin:/bin bash
    experiments/scripts/drift-inject.sh --order random` -> exit=127 + pesan INSTALL
    (host PATH tidak diubah permanen, override satu perintah saja).
  - Cabang shuf positif dibuktikan via shim `shuf` sementara di /tmp (dihapus setelah
    verifikasi): order teracak e.g. `[F D C B G A E]` + note `(urutan acak via shuf)`, exit=0.
  - `--order sequential` tanpa shuf tetap exit=0 (A-G berurutan).
- Q1 dinyatakan CLOSED oleh keputusan operator ini; Q2-Q5 tetap OPEN.
