# Inventaris dan provenance data formal

Dataset formal adalah batch `formal-20261029` yang dikumpulkan pada 29--30
Oktober 2026. Dokumen ini mencatat isi, hitungan baris, taksonomi eksklusi,
hash, batas privasi, dan perintah reproduksi. Revisi kode ada di
[`REVISIONS.md`](REVISIONS.md); peta modul dan aliran data ada di
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Ringkasan batch

| Butir | Nilai |
|---|---|
| Batch | `formal-20261029` |
| Lokasi paket | `experiments/formal-20261029/` (lokal, diabaikan Git) |
| Sel direncanakan | 210 (7 skenario x 2 mode x 15 pengulangan) |
| Sel terminal | 210; 0 tertunda |
| Status terminal | 193 `observed`, 15 `right_censored`, 2 `instrumentation_failure` |
| Baris mentah | 211 (210 sel + 1 percobaan baseline yang diulang) |
| Baris analisis | 207 (192 `observed`, 15 `right_censored`) |
| Baris dieksklusi | 4 |
| Fase analisis | 137 baris R2 (pengulangan 1--10), 70 baris R1 (11--15) |
| Mode | live, satu stack, dua mode berurutan |
| `formal_execution_approved` | `true` (attestation operator, bukan persetujuan metode) |
| `stack_isolated` | `false` |
| `r3_status` | `not_measured` |
| Ukuran paket | 3.026 berkas, sekitar 78 MB; 3.024 berkas berchecksum |

Nilai pembekuan (revisi GitOps, SHA-256 render, revisi skripsi, seed, urutan
mode/skenario, dan konvensi waktu) ada di [`REVISIONS.md`](REVISIONS.md) dan
`experiments/formal-20261029/formal-20261029.manifest.json`.

## Bentuk paket

```
experiments/formal-20261029/
├── formal-20261029.manifest.json     # rencana, status sel, attempts, cooldowns
├── formal-20261029.rows.jsonl        # 211 baris attempt dengan metadata batch
├── formal-20261029.analysis.jsonl    # 207 baris layak analisis (env=manual/gitops)
├── formal-20261029.csv               # jembatan kolom CSV historis
├── formal-20261029.summary.json      # hitungan R1/R2, censoring, exclusions
├── <run_id>.jsonl / <run_id>.csv     # satu baris per attempt
├── <run_id>/                         # 11--14 artefak bukti per run
├── SHA256SUMS                        # 3.024 checksum (dikomit)
└── PROVENANCE.json                   # ringkasan batch dan freeze (dikomit)
```

Satu sel memiliki dua attempt hanya pada `formal-20261029-gitops-C-r08`:
attempt 0 berstatus `baseline_failure`, attempt 1 (`...-retry1`) berstatus
`observed`. Karena itu jumlah direktori run (211) lebih besar daripada jumlah
sel (210).

## Taksonomi eksklusi

Analisis menerima 207 dari 211 baris mentah. Empat baris yang tidak diterima
bukan empat sel yang hilang: tiga sel tidak menghasilkan baris analisis, dan
satu sel tetap dianalisis melalui percobaan ulang.

| Run / attempt | Status mentah | Alasan analyzer | Penyebab | Efek |
|---|---|---|---|---|
| `formal-20261029-gitops-C-r01` | `instrumentation_failure` | `status_not_analyzable` | Kolektor tidak menghasilkan sampel awal, atau metrics-server tidak tersedia | Sel C-r01 tidak punya baris analisis |
| `formal-20261029-gitops-C-r08` (attempt 0) | `baseline_failure` | `status_not_analyzable` | Application `invenio-bootstrap` tidak `Synced/Healthy` sebelum injeksi | Percobaan gagal; sel dianalisis lewat `-retry1` |
| `formal-20261029-gitops-C-r02` | `observed` | `batch_stop` | Run lengkap dan teramati, tetapi proses harness keluar dengan kode 2 | Baris dikecualikan konservatif; dianalisis terpisah di sensitivity |
| `formal-20261029-imperative-G-r05` | `instrumentation_failure` | `status_not_analyzable` | Kegagalan instrumentasi/metrik | Sel G-r05 tidak punya baris analisis |

Pemetaan yang harus dibaca eksplisit:

- **Analyzer** mengelompokkan tiga baris sebagai `status_not_analyzable`
  (C-r01, attempt C-r08, G-r05) dan satu baris sebagai `batch_stop` (C-r02).
- **Prosa skripsi** mengelompokkan empat baris sebagai dua kegagalan
  instrumentasi (C-r01, G-r05), satu kegagalan baseline yang diulang (C-r08),
  dan satu batch stop (C-r02).
- Kedua pengelompokan menunjuk himpunan baris yang sama; perbedaannya hanya
  pada level taksonomi. Jangan menjumlahkan `status_not_analyzable=3` dengan
  "tiga kegagalan instrumentasi"; attempt C-r08 adalah kegagalan baseline,
  bukan instrumentasi.

Attempt `C-r08` yang gagal tetap tersimpan di `rows.jsonl` dan CSV, tetapi
tidak menambah N statistik. Retry memakai id deterministik
`formal-20261029-gitops-C-r08-retry1`; rantai attempt divalidasi oleh
`_validate_raw_chain()` di `analysis/analyze_live.py`.

Catatan inventaris: `formal-20261029.summary.json` hanya mencantumkan tiga sel
terdampak (C-r01, C-r02, G-r05) karena baris C-r08 attempt 0 bukan sel yang
kehilangan analisis; pandangan empat baris mentah ada di
`live_analysis.json.exclusions.rows` dan di tabel Bab IV.

### Status manifest

Manifest mencatat `state: "stopped"`, `stop_reason: "instrumentation_failure"`,
dan `stop_run_id: "formal-20261029-gitops-C-r01"` meskipun seluruh 210 sel sudah
terminal. Ini bukan sel tertunda: `counts.terminal` bernilai 210 dan
`counts.pending` bernilai 0. Runner hanya menulis `state: "complete"` bila tidak
ada satu pun run yang membawa `stop_reason`; batch yang di-resume setelah
kegagalan mempertahankan status `stopped`. Karena itu, **kelengkapan koleksi
dibaca dari `counts.terminal` dan `counts.pending`, bukan dari `state`.**

## Checksum dan identitas keluaran

### Paket batch

```bash
cd experiments/formal-20261029
shasum -a 256 -c SHA256SUMS
```

Hasil yang diharapkan: 3.024 baris `OK`, 0 gagal. Dua berkas provenance yang
dikomit memiliki hash:

| Berkas | SHA-256 |
|---|---|
| `experiments/formal-20261029/SHA256SUMS` | `a685cbc8f6ea816e1c312111eff1eb2051cffccfab05dd7fe6676de06e4a4292` |
| `experiments/formal-20261029/PROVENANCE.json` | `3fae070e22e0ec7d678f46ec0ed5206f67c1ca68cb5b3734e691868243a58936` |

### Paket analisis

```bash
cd experiments/analysis-formal-20261029
shasum -a 256 -c SHA256SUMS
```

Hasil yang diharapkan: 7 baris `OK`, 0 gagal. Tujuh keluaran beku dan
hash-nya:

| Berkas | SHA-256 |
|---|---|
| `live_analysis.json` | `13c17ffd611cbd3e74b4c611aa222fecb59f27d352c6d3bc375bf8eefd327084` |
| `live_overview.tex` | `1acedb974e58a4e350ede7c3b33809b0872a68bd11cc5e112286ee37f676117d` |
| `live_exclusions.tex` | `2c5f0d3d91b7b97677528f26b7ffe1a88780e58ea30c15b79f911664cf4ccc6c` |
| `live_r1.tex` | `dedd3fad310fc3e60e9fab27c2dbb6749f4d4dffab968481df9f542351c8a21e` |
| `live_survival.tex` | `b3aa9ae31539c1311b7e6207b59f8e368ac78015e9af17f147be7ba10362c75a` |
| `live_tests.tex` | `e01cb625cd3960f2b0afb7c0623ba8cde7939172d730d33c092c8bc8eee80d1b` |
| `live_effects.tex` | `257dca2ace010e2bac72ab3881162327f28ac00611ef83016470ba04fdb56a7c` |

Paket analisis bersifat lokal dan diabaikan Git. Checksum di atas adalah
identitas keluaran yang dipakai untuk memverifikasi reproduksi; jangan
mengganti angka di Bab IV dengan keluaran baru tanpa mencatat versi baru.

## Reproduksi analisis

Analisis memakai Python 3.9+ dan standard library saja. Jalankan dari akar
repository:

```bash
python3 experiments/analysis/analyze_live.py \
  --in experiments/formal-20261029/formal-20261029.analysis.jsonl \
  --rows experiments/formal-20261029/formal-20261029.rows.jsonl \
  --out /tmp/formal-20261029-rerun \
  --bootstrap 2000 --seed 20261029 --alpha 0.05
```

Catatan penting: `--seed` baku di kode adalah `20261027`, sedangkan batch formal
memakai `20261029`. Tanpa `--seed 20261029`, interval bootstrap dan keluaran
tidak akan identik dengan paket beku. Perintah di atas menulis tujuh berkas;
bandingkan dengan paket beku:

```bash
diff -r experiments/analysis-formal-20261029 /tmp/formal-20261029-rerun
```

Satu-satunya perbedaan yang diharapkan adalah `SHA256SUMS` yang tidak ditulis
oleh analyzer. Tujuh berkas lain harus identik.

Analisis sensitivitas C-r02:

```bash
python3 experiments/sensitivity/c_r02_sensitivity.py \
  --out /tmp/c-r02-sensitivity.json
```

Skrip ini tidak menulis ke direktori beku dan menolak `--out` di dalam
`experiments/formal-20261029/` atau
`experiments/analysis-formal-20261029/`. Nilai yang dihasilkan (misalnya
Cliff's delta pemulihan C turun dari 0,75 ke 0,64) tidak memiliki berkas
keluaran yang dikomit; lihat
[`docs/reproducibility/claim-traceability.md`](../docs/reproducibility/claim-traceability.md)
untuk status buktinya.

Verifikasi instrumen offline:

```bash
python3 -m unittest discover -s experiments/tests -q          # 491 tes
python3 -m unittest discover -s experiments/sensitivity -p 'test_*.py' -q  # 9 tes
```

## Privasi dan batas berbagi

- Data mentah dan bukti per run hanya tersimpan lokal; `.gitignore` mengecualikan
  `experiments/formal-20261029/*/`, `*.jsonl`, `*.csv`, `*.manifest.json`, dan
  `*.summary.json`. Hanya `SHA256SUMS` dan `PROVENANCE.json` yang dikomit.
- Token Invenio tidak pernah masuk argumen, log, manifest, CSV, summary, atau
  bukti. Nilai `Secret`/`SealedSecret` tidak dipilih sebagai bidang dan tidak
  diserialisasi; perbandingan rahasia hanya berupa boolean kesetaraan di memori.
- `experiments/evidence-local/` (sekitar 41 MB) berisi arsip batch yang dihentikan
  dan investigasi lokal. Arsip itu bukan salinan off-site, bukan backup
  disaster-recovery, dan belum melalui peninjauan publikasi.
- Sebelum membagikan paket mentah, lakukan peninjauan manual untuk materi
  sensitif. Keberhasilan desain logging bukan bukti bahwa tidak ada rahasia di
  dalam berkas.
- Checksum membuktikan integritas byte, bukan kelayakan publikasi.
