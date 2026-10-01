# Subjek Eksperimen (Surrogate S1/S2)

Surrogate minimal untuk kelas workload komposit multi-service (Bab 3).
Bukan replika InvenioRDM; hanya apparatus pengukuran R1-R3.

Placeholder namespace: `EXP_NS`. Ganti sebelum apply:
`sed 's/EXP_NS/<ns>/g' manifests.yaml | kubectl apply --dry-run=client -f -`

Namespace eksperimen yang diizinkan (jangan pakai namespace lain):
`exp-s1-manual`, `exp-s1-gitops`, `exp-s2-manual`, `exp-s2-gitops`.

## S1 — `subjects/s1/manifests.yaml` (5 resources, namespace `EXP_NS`)

| # | Kind | Name | Baseline |
|---|------|------|----------|
| 1 | Deployment | `exp-web` | `replicas=3`, `image=nginx:1.25.3` |
| 2 | Service | `exp-web` | `ClusterIP 80->80` |
| 3 | ConfigMap | `exp-web-config` | `LOG_LEVEL=info`, `DATABASE_URL=postgres://db:5432/app` |
| 4 | Secret | `exp-web-secret` | `username=exp-user`, `password=exp-secret-123` (base64) |
| 5 | CronJob | `exp-web-tick` | `schedule=*/5 * * * *`, `image=busybox:1.36` |

## S2 — `subjects/s2/manifests.yaml` (7 resources = isi S1 + 2)

| # | Kind | Name | Baseline / Keterangan |
|---|------|------|------------------------|
| 1-5 | (sama dengan S1) | `exp-web`, `exp-web`, `exp-web-config`, `exp-web-secret`, `exp-web-tick` | Identik dengan S1, label `subject: s2` |
| 6 | PersistentVolumeClaim | `exp-store-data` | `1Gi`, `ReadWriteOnce` |
| 7 | StatefulSet | `exp-store` | `replicas=1`, `image=nginx:1.25.3`, mount PVC `exp-store-data` ke `/usr/share/nginx/html`, `serviceName: exp-web` |

Validasi kering (tanpa `--live`, tanpa menyentuh klaster):
`sed 's/EXP_NS/exp-s1-manual/g' experiments/subjects/s1/manifests.yaml | kubectl apply --dry-run=client -f -`
`sed 's/EXP_NS/exp-s2-manual/g' experiments/subjects/s2/manifests.yaml | kubectl apply --dry-run=client -f -`
