# Harness eksperimen live InvenioRDM

**Status: implementasi offline-tested, dry-run default.** Dokumen ini bukan izin
eksekusi. Tidak ada run klaster yang dilakukan saat harness ini dibuat. Seluruh
gerbang formal pada `experiments/LIVE-OBSERVER.md` dan Bab III tetap berlaku;
uji offline tidak membuktikan klaster, seed, audit, kapasitas, atau metode siap.

Harness menargetkan **satu stack InvenioRDM nyata**:

| Peran | Nama nyata |
|---|---|
| Namespace default | `invenio` (namespace eksperimen harus `exp-*`) |
| Argo Application | `invenio-bootstrap`, dikelola app-of-apps `apps` |
| Deployment | `invenio-web` (container `web`) |
| HPA | `invenio-web-hpa` → `Deployment/invenio-web` |
| ConfigMap | `invenio-app-config-<hash>` yang dirujuk `envFrom` |
| SealedSecret | `invenio-app-secrets` (metadata saja) |
| Service | `invenio-web` |

Subjek NGINX lama (`exp-web`, S1/S2) **tidak** dipakai. Harness tidak membuat
namespace lengan kembar dan menolak run bila ada lebih dari satu stack
`invenio-web` pada namespace berbeda.

## Berkas

| Berkas | Fungsi |
|---|---|
| `run_one.py` | CLI satu run; default dry-run, `--live` untuk mutasi nyata |
| `harness.py` | arm control, snapshot, kontrak R1, injeksi, repair, kolektor, timeline |
| `convert.py` | konversi JSONL ke kolom CSV analisis historis |
| `runs/` | keluaran runtime; diabaikan Git |

## Dry-run (default, tanpa klaster)

```bash
python3 experiments/live/run_one.py \
  --arm imperative --scenario B --rep 1 \
  --namespace invenio --out /tmp/invenio-live-dry
```

Dry-run **tidak menjalankan `kubectl` atau HTTP apa pun**. Keluarannya satu baris
JSONL, satu CSV, dan `planned_mutations`; semua waktu dan R1 `null`. Tidak ada
token yang diminta atau dibaca.

## Live (hanya setelah izin formal)

```bash
export INVENIO_TOKEN=...   # jangan pernah ditulis ke argumen, log, atau bukti
python3 experiments/live/run_one.py \
  --arm gitops --scenario B --rep 1 \
  --namespace exp-arm-a --app invenio-bootstrap \
  --confirm-single-stack --live \
  --source-revision <40-hex> --render-sha256 <64-hex> \
  --timeout 300 --sample-interval 1 --imperative-interval 5 \
  --out experiments/live/runs
```

Syarat `--live` bersifat fail-closed:

1. `--confirm-single-stack` wajib.
2. `--namespace` dan `--app` wajib eksplisit; nilainya tidak diambil dari
   default dry-run.
3. Namespace harus `invenio` atau `exp-*`; namespace karantina selalu
   `exp-<namespace>-drift`.
4. `INVENIO_TOKEN` wajib; verifikasi seed memakai API Invenio dan berhenti bila
   token hilang, draf/berkas tidak ada, ukuran/checksum tidak cocok.
5. `--source-revision` dan `--render-sha256` wajib; keduanya dibekukan sebelum
   run, bukan direkonstruksi setelah hasil terlihat. Revisi harus sama dengan
   revisi yang teramati pada `invenio-bootstrap`, jika tidak harness berhenti.
6. Preflight menolak bila `invenio-web` ada di lebih dari satu namespace, bila
   Application tidak menunjuk namespace target, atau bila namespace karantina
   sudah ada.

> Namespace produksi `invenio` secara teknis diizinkan oleh guard untuk
> kalibrasi/inspeksi, tetapi **bukan** lingkungan formal. Bab III mewajibkan
> namespace eksperimen terpisah dan salinan stack yang setara. Jangan menjalankan
> blok formal di `invenio`.

## Prosedur dua lengan berurutan

Hanya satu lengan aktif pada satu waktu. Urutan lengan diacak dan dicatat;
urutan skenario memakai permutasi yang sama di kedua lengan.

### Lengan `gitops`

1. Verifikasi `apps` **dan** `invenio-bootstrap` memiliki
   `spec.syncPolicy.automated` dengan `selfHeal: true`.
2. Jangan menambal Application. Baseline mensyaratkan keduanya
   `Synced/Healthy`.
3. ArgoCD melakukan rekonsiliasi; harness hanya mengamati.

### Lengan `imperative`

1. Sebelum aktivasi, **keduanya** harus masih auto-sync/selfHeal. Bila salah satu
   sudah pause, run ditolak (tidak menumpuk keadaan lengan).
2. Simpan `spec` Application asli yang tersanitasi sebagai bukti.
3. Pause `apps` lebih dulu, lalu `invenio-bootstrap`, dengan merge patch
   `{"spec":{"syncPolicy":{"automated":null}}}`. Verifikasi keduanya benar-benar
   berhenti.
4. Jalankan baseline, injeksi, dan pemeriksa/runbook otomatis. Pemeriksa hanya
   menerima kontrak bidang baseline, bukan label skenario; koreksi memakai
   `kubectl` tetap.
5. Di `finally`, pulihkan `invenio-bootstrap` lalu `apps` ke nilai `automated`
   asli, verifikasi, dan laporkan kegagalan restore. Application tidak pernah
   dihapus.
6. Setelah restore, verifikasi postcondition dua pembacaan; kegagalan dilaporkan
   sebagai `reset_failure`, bukan dibuang.

Kegagalan pause/restore, ketidakcocokan keadaan lengan, atau namespace tidak aman
menghentikan run sebelum/sesudah mutasi dan menghasilkan exit nonzero.

## Skenario

| Skenario | Objek nyata | Injeksi | Pemulihan | Atribusi/analisis |
|---|---|---|---|---|
| A | `Deployment/invenio-web`, `HPA/invenio-web-hpa` | `spec.replicas` ke bawah minimum HPA (2→1) | HPA mengembalikan replika | Kontrol HPA; `/spec/replicas` dikecualikan dari R1 statis; bukan efikasi ArgoCD/imperatif |
| B | container `web` | tag image sintetis `...:drift-<id>` | digest image baseline dari snapshot | Drift terkelola; ArgoCD atau runbook |
| C | `invenio-app-config-<hash>` | key non-rahasia `INSTANCE_TAGLINE` | data baseline | Drift terkelola; adopsi runtime dilaporkan terpisah |
| D | `Deployment/invenio-web` | hapus objek | manifest Deployment baseline tersanitasi (tanpa `replicas` milik HPA); render beku tetap gerbang formal | Drift terkelola; kesetaraan objek, bukan status rollout |
| E | container `web` | limit memori `2Gi` → `1536Mi` | nilai baseline | Drift terkelola |
| F | salinan `invenio-web` | buat di `exp-<namespace>-drift`, replika 0 | harness menghapus di `finally` | Batas visibilitas; objek di luar Application tidak diharapkan dipangkas ArgoCD |
| G | `SealedSecret/invenio-app-secrets` | **hanya** anotasi metadata `experiment.invenio.ugm/drift` | hapus anotasi / restore baseline | Tidak pernah membaca atau menulis `spec.encryptedData`; atribusi ArgoCD/imperatif/lainnya dicatat |

Setiap injeksi memverifikasi bidang sasaran berubah dari pembacaan balik sebelum
jendela pengamatan dimulai. Bila tidak berubah: `invalid_injection`, bukan waktu
deteksi nol. Tidak ada penghapusan seed/record, purge queue, restore, atau
perubahan pengendali.

## Pengukuran dan penyensoran

- `t0` = permintaan injeksi dikirim; `t_a` = respons API diterima; verifikasi
  bidang harus selesai sebelum pengamatan dimulai. Batas timeout tetap dihitung
  dari `t0` agar selaras dengan kontrak v2; verifikasi yang terlalu lama tidak
  memberi waktu pengamatan tambahan.
- `t_d` = sinyal pengendali pertama: `imperative` (pemeriksa), `argocd`
  (`OutOfSync`/operation), atau `hpa` (perubahan status/scale HPA).
- `t_e` = bukti tersimpan pertama berupa diff/snapshot tersanitasi yang
  mengidentifikasi objek dan bidang. Untuk A, bukti adalah sampel status HPA.
  `t_e` dapat mendahului `t_d` karena kolektor pasif tidak menunggu pengendali.
- `t_r` = pembacaan pertama seluruh kontrak kembali cocok, dikonfirmasi pembacaan
  berikutnya. A juga mensyaratkan HPA settled; F mensyaratkan tidak ada objek
  karantina. Dua pembacaan harus berurutan.
- Durasi dihitung dari satu jam monotonik host, bukan selisih UTC. UTC disimpan
  untuk audit.
- Timeout: `*_seconds = null`, status `right_censored`, `censor_seconds` = batas
  beku. Tidak ada interpolasi dan tidak ada nol untuk sinyal yang hilang.
- Deteksi tidak teramati tetapi pemulihan lebih dulu berhenti:
  `unobserved_before_stop`. Kegagalan API/instrumentasi: `instrumentation_failure`.
  Kegagalan perintah koreksi: `recovery_failure`. Postcondition gagal:
  `reset_failure`.
- R1 = persentase resource yang **seluruh bidang terpilihnya** cocok, dengan
  penyebut kontrak baseline yang sama. `/spec/replicas` dikecualikan untuk
  Deployment milik HPA; status HPA dilaporkan terpisah. Objek karantina F tidak
  masuk penyebut; keberadaannya dicatat di `extra_resources`.
- Secret hanya dibandingkan sebagai keberadaan/anotasi metadata; nilai
  `Secret`/`SealedSecret` tidak pernah masuk bukti.

## Keluaran dan bukti

`<out>/<run_id>.jsonl` — satu baris hasil; `<out>/<run_id>.csv` — kolom analisis.
Direktori `<out>/<run_id>/` menyimpan:

| Berkas | Isi |
|---|---|
| `baseline.json` | snapshot baseline tersanitasi, HPA, pod/node |
| `contract.json` | kontrak inventory/bidang, `baseline_sha256`, revisi/render |
| `samples.jsonl` | setiap sampel: resource fields, HPA, status Argo, ekstra |
| `injection.json` | `t0`/`t_a`/verifikasi, bidang berubah, perintah |
| `imperative.json` | deteksi, bukti, perintah koreksi, kegagalan |
| `arm.json` | spec Application asli dan keadaan pause |
| `cleanup.json` | hasil pembersihan karantina |
| `postcondition.json` | dua pembacaan pascakoreksi |
| `commands.jsonl` | log perintah mutasi (tanpa token/Secret) |
| `diff-*.json` | diff tersanitasi pertama |

Kolom JSONL utama: `run_id`, `env`/`arm`, `scenario`, `rep`, `status`,
`t0_*`, `t_a_*`, `t_d_*`, `t_e_*`, `t_r_*`, `detection_seconds`,
`evidence_seconds`, `recovery_seconds`, `*_status`, `censor_seconds`,
`max_sample_gap_seconds`, `observation_end_*`, `collector_started_*`,
`detection_controller`, `recovery_controller`, `detection_ref`, `evidence_ref`,
`r1_baseline`, `r1_first`, `r1_last`, `kubectl_cmds`, `analysis_group`,
`efficacy_eligible`, `source_revision`, `render_sha256`, `baseline_sha256`.

### Pemetaan CSV historis

`python3 experiments/live/convert.py --in <run>.jsonl --out <run>.csv`

| Kolom lama | Nilai live | Catatan |
|---|---|---|
| `subject` | `invenio-live` | bukan S1/S2 |
| `env` | `manual` untuk `imperative`, `gitops` | label lama |
| `skenario` | `scenario` | A–G |
| `rep` | `rep` | indeks |
| `t0` | `t_a - t0` | latensi acknowledgement injeksi |
| `td` | `t_d - t0` | deteksi pengendali |
| `trci` | `t_e - t0` | **nama lama**; bukti deviasi, bukan waktu akar masalah manusia |
| `t2` | `t_r - t0` | pemulihan terkonfirmasi |
| `r1_t0/t1/t2` | baseline/first/last | persen |
| `kubectl_cmds` | jumlah perintah koreksi terukur | 0 untuk gitops; cleanup tidak dihitung |
| `notes` | status, controller, sensor, cleanup, restore | tanpa token/Secret |

Nilai hilang ditulis kosong, **bukan 0**. CSV ini adalah jembatan arsip, bukan
izin menjalankan `experiments/analysis/analyze.py` (analyzer itu mock-only dan
menolak subjek non-S1/S2). `summarize.py` v2 memakai `env=manual`; baris live
memakai `imperative` dan harus dipetakan sebelum analisis formal apa pun.

## Gerbang formal yang belum tertutup

1. **Namespace eksperimen**: stack `invenio` produksi belum disalin ke namespace
   `exp-*`; dua lingkungan A/B nyata belum tersedia.
2. **Audit API**: belum ada bukti audit; unsur pelaku R3 tetap
   `tidak dapat dinilai`.
3. **Salinan seed per lengan**: seed `4ben9-bgh38` adalah draf produksi; salinan
   di namespace eksperimen beserta SHA-256 belum diverifikasi. Verifikasi seed
   harness memakai token dan gagal tertutup, tetapi tidak menciptakan salinan.
4. **Versi runtime**: ArgoCD, CNPG, OpenSearch, MinIO, dan chart belum dibekukan
   pada revisi yang benar-benar berjalan.
5. **Render dan revisi**: `--source-revision`/`--render-sha256` harus berasal dari
   ekspor render beku; harness tidak membuktikan autentisitas ekspor.
6. **Metode**: tinjauan pemilik/pembimbing untuk lengan imperatif terotomasi,
   kontrol HPA, keluarga uji, dan penanganan data tersensor.
7. **Kapasitas, NTP, SMTP, HA OpenSearch**: bukti jendela beban, sinkronisasi jam,
   relay email, dan HA belum ada; tidak boleh menjadi prasyarat diam-diam.
8. **Pilot tak terukur**: belum ada run live yang ditinjau; harness ini belum
   diuji pada klaster.

## Keselamatan dan pengujian

- Dry-run tidak memanggil `subprocess`/HTTP; live membutuhkan `--live` eksplisit.
- Namespace di luar `invenio`/`exp-*` ditolak; karantina selalu `exp-*`.
- Tidak ada penghapusan seed/record, purge queue, restore, migrasi, atau
  perubahan Secret plaintext.
- Pembersihan karantina dan restore Application berjalan di `finally`;
  kegagalannya dilaporkan dan membuat exit nonzero. Harness hanya menghapus
  namespace karantina yang memiliki label `run-id` milik run ini; namespace
  milik pihak lain tidak disentuh.
- Token hanya dari `INVENIO_TOKEN`, tidak pernah masuk argumen, log, atau bukti.
- `kubectl` dipanggil sebagai argumen list, tanpa shell.

```bash
python3 -m unittest discover -s experiments/tests -v
python3 -m py_compile experiments/live/*.py
bash -n experiments/scripts/*.sh
shellcheck experiments/scripts/*.sh
git diff --check
```
