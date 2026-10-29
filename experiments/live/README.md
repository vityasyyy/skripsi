# Harness eksperimen live InvenioRDM

**Status: implementasi offline-tested, dry-run default.** Dokumen ini bukan izin
eksekusi. Pilot terbatas 27 Oktober 2026 berhasil dan tetap bukti pilot, bukan
data formal. Percobaan formal yang tidak lengkap dihentikan; tidak ada
peluncuran formal baru yang disetujui. Perubahan ini tidak menjalankan klaster.
Gerbang formal yang tersisa pada `experiments/LIVE-OBSERVER.md` dan Bab III tetap
berlaku; uji offline tidak membuktikan klaster, seed, kapasitas, recovery, atau
metode siap. Batch formal 210 run (`run_matrix.py`) belum diselesaikan pada
klaster.

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
| `run_matrix.py` | Orkestrator batch 210 run; manifest, resume, ringkasan R1/R2 |
| `harness.py` | arm control, snapshot, kontrak R1, injeksi, repair, kolektor, timeline |
| `declaration.py` | loader deklarasi render beku, seleksi empat resource, validasi identitas/bidang |
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

## Batch formal 210 run

Batch adalah **2 lengan × 7 skenario × 15 replikasi = 210 run** pada satu stack,
berurutan, bukan dua lingkungan serentak:

- Repetisi **1--10** adalah blok **R2** (waktu deteksi, bukti, pemulihan).
- Repetisi **11--15** adalah blok **R1** (konsistensi).
- Urutan lengan diacak dari `--seed`; kedua lengan memakai **permutasi skenario
  yang sama**. Seed, urutan lengan, dan permutasi dicatat di manifest.
- `run_matrix.py` memanggil `harness.main` untuk setiap run, sehingga gate token,
  satu stack, arm, reset, dan no-overwrite per run tetap di `harness.py`.
- Batch memakai `--baseline-timeout 300` secara default agar HPA sempat settle
  setelah blok pengujian sebelumnya; nilai ini dicatat sebagai bagian protokol.
- Batch memakai `--cooldown-seconds 60` dan `--baseline-retries 1` secara default;
  lihat bagian cooldown dan retry di bawah.

Dry-run default (tanpa `kubectl`/HTTP):

```bash
python3 experiments/live/run_matrix.py \
  --arms gitops imperative --scenarios A-G --reps 15 --seed 20261027 \
  --namespace invenio --out /tmp/invenio-batch-dry
```

Live hanya setelah izin formal dan setelah seluruh gate pada
`experiments/LIVE-OBSERVER.md` tertutup:

```bash
export INVENIO_TOKEN=...   # jangan pernah ditulis ke argumen, log, atau bukti
python3 experiments/live/run_matrix.py \
  --live --confirm-single-stack --production-like \
  --arms gitops imperative --scenarios A-G --reps 15 --seed 20261027 \
  --namespace invenio --app invenio-bootstrap \
  --render-file /path/to/invenio-frozen-render.json \
  --source-revision <40-hex> --render-sha256 <64-hex> \
  --out experiments/live/runs/formal-<batch-id>
```

`--production-like` hanya anotasi penerimaan operator; lihat batasnya di bawah.
Tanpa flag itu batch live tetap boleh berjalan sebagai pilot, tetapi semua baris
batch mencatat `formal_execution_approved: false`.

Batch berhenti pada status `invalid_injection`, `instrumentation_failure`,
`reset_failure`, `recovery_failure`, `cleanup_failure`, `arm_restore_failure`,
atau kegagalan keras lain (arm state, safety refusal, nonzero exit). Kegagalan
baseline pra-injeksi adalah satu-satunya pengecualian dan hanya boleh di-retry
sesuai `--baseline-retries`; bila retry habis, batch berhenti. Run yang gagal,
manifest, dan bukti per-run dipertahankan; run berikutnya tidak dijalankan.
Untuk meneruskan sisa run setelah kegagalan:

```bash
python3 experiments/live/run_matrix.py \
  --live --confirm-single-stack --production-like \
  --namespace invenio --app invenio-bootstrap \
  --render-file /path/to/invenio-frozen-render.json \
  --source-revision <40-hex> --render-sha256 <64-hex> \
  --out experiments/live/runs/formal-<batch-id> --resume
```

Resume hanya menerima manifest yang cocok dengan rencana (seed, lengan,
skenario, replikasi, namespace, app, revisi, render, mode, flag cooldown/retry)
dan tidak pernah menimpa run terminal. Run terminal tidak diulang. Berkas
render dibaca dan di-hash ulang pada setiap invokasi; isi/revisi/hash yang
berubah tidak dapat melanjutkan batch beku, dan path saja bukan identitas.
Kegagalan baseline yang masih memiliki jatah retry tercatat sebagai `retrying` dan
dilanjutkan dengan id retry yang sama; kegagalan terminal tetap gagal. Untuk
mengulang sel yang gagal, buat batch baru dengan `--batch-id`/`--out` baru.
Tanpa `--batch-id`, id batch diturunkan secara deterministik dari rencana dan
konfigurasi, sehingga pengulangan perintah yang sama akan ditolak sebelum
menimpa apa pun.

## Cooldown kapasitas dan retry baseline

Batch berjalan berurutan pada satu stack yang juga menampung HPA
`invenio-web-hpa` (maksimum 4/4, utilisasi memori sekitar 90% request) dan node
pada 65--67%. Batch kontinu pernah mendorong salah satu node melewati gate
memori 70%. Dua knob berikut menjaga kapasitas tanpa mengubah protokol statistik:

- `--cooldown-seconds` (default `60`) — jeda setelah setiap run terminal dan
  sebelum run berikutnya. Tidak ada jeda setelah run terakhir dan tidak ada jeda
  di awal batch. Setiap jeda dicatat di `cooldowns` manifest dengan
  `after_run_id`, `next_run_id`, `requested_seconds`, `started_utc`,
  `finished_utc`, `elapsed_seconds`, dan `applied`. Dry-run mencatat entri
  dengan `applied: false` dan `elapsed_seconds: 0.0`; dry-run tidak benar-benar
  tidur.
- `--baseline-retries` (default `1`) — jumlah retry untuk **kegagalan baseline
  pra-injeksi saja**. Retry hanya diterima bila `status: baseline_failure`,
  tidak ada injeksi diterima, tidak ada `t0`, tidak ada mutasi, cleanup `ok`,
  dan arm restore `restored`. Attempt gagal tetap disimpan sebagai bukti di
  `<out>/<run_id>.jsonl` dan direktori buktinya; retry memakai id deterministik
  `<run_id>-retry1` (lalu `-retry2`, ...). Manifest mencatat `attempts` per sel
  (`attempt`, `retry_of`, status, waktu, `exit_code`, `stop_reason`, `error`,
  `row_path`) sehingga hubungan dan urutan tetap auditabel.
- Retry dijalankan setelah cooldown. Bila retry juga gagal, batch berhenti
  (`state: stopped`, `stop_run_id` menunjuk attempt terakhir) dan sisa run tetap
  `pending`. Kegagalan injeksi, instrumentasi, recovery, reset, cleanup, arm
  restore, atau arm state **tidak pernah** di-retry.

Cooldown dan retry **tidak** melonggarkan gate kapasitas: `baseline_gate`
tetap otoritatif. Pod yang belum Running/Ready, HPA yang belum settle, dan node
dengan CPU atau memori valid >= 70% ditunggu sampai `--baseline-timeout`; objek
wajib yang hilang, target HPA yang salah, karantina/kontaminasi, atau telemetri
yang tidak valid/tidak lengkap menghentikan run segera. HPA min/max dan resource
request tidak diubah siapa pun.

Retry adalah artefak pemulihan protokol, **bukan sampel tambahan**. Rencana
tetap 210 sel; `analysis.jsonl` memakai attempt terakhir tiap sel, sehingga satu
sel tetap satu observasi. Attempt baseline yang gagal tetap muncul di
`rows.jsonl`/CSV sebagai bukti, tetapi tidak masuk `analysis.jsonl` maupun
hitungan statistik.

## Live (hanya setelah izin formal)

```bash
export INVENIO_TOKEN=...   # jangan pernah ditulis ke argumen, log, atau bukti
python3 experiments/live/run_one.py \
  --arm gitops --scenario B --rep 1 \
  --namespace exp-arm-a --app invenio-bootstrap \
  --confirm-single-stack --live \
  --render-file /path/to/invenio-frozen-render.json \
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
5. `--render-file`, `--source-revision`, dan `--render-sha256` wajib. Berkas
   render dibaca **satu kali**, di-hash dari byte yang benar-benar di-parse, lalu
   divalidasi sebelum HTTP Invenio atau aktivasi lengan: format
   `invenio-frozen-render-v1`, revisi 40 heksadesimal sama dengan
   `--source-revision` dan revisi Argo yang teramati, SHA-256 sama dengan
   `--render-sha256`, objek bertarget unik, namespace benar, dan seluruh bidang
   terpilih ada. Input yang hilang, berubah, duplikat, non-finit, atau tidak
   konsisten ditolak tanpa mencetak isi berkas. Revisi/render tidak boleh
   direkonstruksi setelah hasil terlihat.
6. Preflight menolak bila `invenio-web` ada di lebih dari satu namespace, bila
   Application tidak menunjuk namespace target, atau bila namespace karantina
   sudah ada.

> Namespace `invenio` adalah satu-satunya stack nyata yang dipilih untuk desain
> satu stack berurutan. Izin guard bukan sertifikasi kesiapan formal: eksekusi
> tetap menunggu gerbang pada `experiments/LIVE-OBSERVER.md`, pembekuan,
> persetujuan pembimbing, kapasitas, seed, dan reset yang terverifikasi.

## Oracle R1 beku (deklarasi independen)

Nilai harapan R1 **tidak lagi** diambil dari baseline live. Baseline live yang
sudah berubah tidak boleh mensertifikasi dirinya sendiri. Kedua entrypoint live
(`run_one.py`/`harness.py` dan `run_matrix.py`) menerima `--render-file`: ekspor
render GitOps beku dalam JSON dengan bentuk:

```json
{
  "format": "invenio-frozen-render-v1",
  "source_revision": "<40 heksadesimal huruf kecil>",
  "objects": [{"apiVersion": "...", "kind": "...", "metadata": {...}, "...": "..."}]
}
```

`--render-sha256` adalah SHA-256 dari **byte berkas yang benar-benar di-parse**.
Loader stdlib membaca byte satu kali, menghitung hash dari byte itu, lalu
mem-parse byte yang sama; berkas tidak dibaca ulang antara verifikasi dan
pemakaian. Format, revisi, hash, objek, namespace, dan bidang terpilih
divalidasi sebelum HTTP Invenio, aktivasi lengan, atau injeksi. Dry-run tidak
memerlukan berkas render dan tetap tidak melakukan subprocess/HTTP.

Objek yang dipilih tepat empat, bukan seluruh render:

| Resource | Bidang terpilih |
|---|---|
| `Deployment/invenio-web` | image container `web`; `requests`/`limits` CPU dan memori |
| `ConfigMap/invenio-app-config-<hash>` | seluruh `data`; identitas diambil dari `envFrom.configMapRef` container `web` yang dideklarasikan, bukan dari pod live |
| `Service/invenio-web` | `spec.type`, selector `app.kubernetes.io/name`, port pertama dan `targetPort` |
| `SealedSecret/invenio-app-secrets` | hanya anotasi `experiment.invenio.ugm/drift`; `spec.encryptedData` tidak pernah dibaca atau disimpan |

Render penuh boleh memuat objek aplikasi lain; objek di luar empat target
diabaikan. Identitas target ganda, target hilang, namespace salah, referensi
ConfigMap yang ambigu/hilang, bidang terpilih hilang, atau anotasi drift yang
sudah ada di deklarasi ditolak, bukan ditebak.

R1 = persentase resource yang **seluruh bidang terpilihnya** cocok
(4 resource = 100%, 3 = 75%). Setiap baris menyimpan `r1_baseline_details`,
`r1_first_details`, dan `r1_last_details` berisi identitas resource, status
cocok, dan mismatch yang tersanitasi; agregat `r1_baseline`/`r1_first`/
`r1_last` dihitung dari logika pembanding yang sama. Observasi yang tidak ada
tetap `null`, bukan match ciptaan. `/spec/replicas` milik HPA tetap dikecualikan
dari bidang Deployment; status HPA baseline disimpan terpisah untuk kontrol
skenario A.

Baseline live diverifikasi terhadap deklarasi sebelum injeksi. Bila berbeda,
run berhenti sebagai `baseline_failure` dengan alasan
`declaration_mismatch`; harness **tidak** memperbaiki baseline secara otomatis
dan **tidak** memakai nilai live sebagai default. Manifest pemulihan Deployment
dibangun dari deklarasi dan tidak pernah memuat `replicas`; nilai replika
skenario A diambil dari status HPA baseline yang teramati, bukan dari deklarasi.

Dua ekuivalensi sempit diterapkan pada pembanding dan pembacaan balik injeksi:

- `Service.spec.type` yang dihilangkan sama dengan `ClusterIP`;
- kuantitas Kubernetes dievaluasi dengan logika kuantitas yang ada, sehingga
  `1000m` = `1` dan `2Gi` = `2048Mi`.

Tidak ada normalisasi string lain. Patch pemulihan memakai nilai mentah
deklarasi (string kuantitas yang valid), bukan nilai hasil normalisasi, dan
verifikasi injeksi tetap memeriksa perubahan yang benar-benar terjadi.

### Resep persiapan render beku

Resep ini offline dan tidak dijalankan oleh harness. Gunakan checkout/arsip
GitOps yang tidak berubah, renderer Kustomize yang sudah ada, dan PyYAML yang
sudah terpasang; tidak ada framework renderer baru, unduhan, atau instalasi.

```bash
# 1. Checkout imutabel pada revisi yang dibekukan.
git clone https://github.com/vityasyyy/invenio-rdm-gitops.git /tmp/invenio-rdm-gitops
cd /tmp/invenio-rdm-gitops
git checkout --detach <40-hex>
test "$(git rev-parse HEAD)" = "<40-hex>"
test -z "$(git status --porcelain)"

# 2. Render dengan entrypoint Kustomize yang sudah ada.
kustomize build k8s/apps/invenio/kustomization.yaml > /tmp/invenio-render.yaml

# 3. Konversi offline ke JSON dan cetak hash byte.
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import yaml

revision = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True).strip()
documents = [item for item in yaml.safe_load_all(
    Path("/tmp/invenio-render.yaml").read_text()) if item]
bundle = {
    "format": "invenio-frozen-render-v1",
    "source_revision": revision,
    "objects": documents,
}
data = json.dumps(
    bundle, sort_keys=True, indent=2, ensure_ascii=False).encode() + b"\n"
Path("/tmp/invenio-frozen-render.json").write_bytes(data)
print(hashlib.sha256(data).hexdigest())
PY

# 4. Catat hash dan versi alat di catatan pembekuan.
shasum -a 256 /tmp/invenio-frozen-render.json
kustomize version
python3 -c 'import sys, yaml; print(sys.version); print(yaml.__version__)'
```

Kuantitas Kubernetes harus tetap berupa string pada render (misalnya `"1"`,
`"250m"`, `"2Gi"`). Loader menolak angka mentah untuk bidang kuantitas; itu
adalah cacat render, bukan alasan untuk mengoersi nilai. Simpan berkas lengkap
secara lokal untuk verifikasi pembekuan; hanya kontrak tersanitasi, hash,
identitas, dan detail mismatch yang ditulis ke bukti. Versi yang teramati saat
resep ini ditulis: Kustomize v5.8.1, kubectl v1.37.1, Python 3.12.8, PyYAML
6.0.3; repository tidak mem-pin versi tersebut, jadi catatan pembekuan harus
memakai versi aktual.

**Batas provenance.** Hash dan revisi yang dideklarasikan membuktikan integritas
byte dan kesesuaian revisi, **bukan** bahwa berkas benar-benar dihasilkan dari
commit tersebut. Catat URL checkout, revisi, `git status --porcelain` kosong,
perintah render, versi Kustomize/Python/PyYAML, dan hash hasil di catatan
pembekuan. Jangan memberi label ulang pada hash lama atau mengattest berkas
arbitrer sebagai terverifikasi sumber. Regenerasi yang berbeda harus menjadi
artefak beku baru dengan hash dan catatan baru.

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
| A | `Deployment/invenio-web`, `HPA/invenio-web-hpa` | `spec.replicas` ke bawah minimum HPA (dari status HPA baseline) | HPA mengembalikan replika | Kontrol HPA; `/spec/replicas` dikecualikan dari R1 statis; bukan efikasi ArgoCD/imperatif |
| B | container `web` | tag image sintetis `...:drift-<id>` | image deklarasi beku | Drift terkelola; ArgoCD atau runbook |
| C | `invenio-app-config-<hash>` | key non-rahasia `INSTANCE_TAGLINE` | data deklarasi beku | Drift terkelola; adopsi runtime dilaporkan terpisah |
| D | `Deployment/invenio-web` | hapus objek | manifest Deployment dari deklarasi beku (tanpa `replicas` milik HPA) | Drift terkelola; kesetaraan objek, bukan status rollout |
| E | container `web` | limit memori `2Gi` → `1536Mi` | nilai deklarasi beku | Drift terkelola |
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
  penyebut empat resource dari deklarasi beku yang sama. `/spec/replicas`
  dikecualikan untuk Deployment milik HPA; status HPA dilaporkan terpisah.
  Objek karantina F tidak masuk penyebut; keberadaannya dicatat di
  `extra_resources`. Per-resource match/mismatch disimpan di
  `r1_baseline_details`, `r1_first_details`, dan `r1_last_details`.
- Secret hanya dibandingkan sebagai keberadaan/anotasi metadata; nilai
  `Secret`/`SealedSecret` tidak pernah masuk bukti.

### Baseline readiness, node, dan batas waktu

- `stabilize_baseline()` membaca snapshot, pod, lalu node secara berurutan.
  Hanya kegagalan sementara berikut yang ditunggu sampai `--baseline-timeout`:
  pod belum Running/Ready, HPA belum settle, dan node dengan persentase valid
  >= 70%. Setiap penolakan mereset riwayat dua pembacaan yang cocok.
  Objek wajib hilang, target HPA salah, karantina/kontaminasi, dan telemetri
  tidak valid/tidak lengkap langsung gagal tertutup.
- Dua pembacaan konfigurasi yang berurutan dan cocok adalah kriteria penerimaan
  di bawah timeout, **bukan** klaim periode hening panjang. Deadline diperiksa
  sebelum keberhasilan diterima, dan tidur dibatasi sisa anggaran waktu.
- Setiap observasi readiness yang ditolak disimpan di `readiness.json` beserta
  alasan, waktu, batas akuisisi, pod, node, HPA, status Argo, dan objek karantina.
  Berkas ini tetap ditulis saat baseline gagal, termasuk ketika `baseline.json`
  bernilai `null`; snapshot resource tidak disalin agar Secret/SealedSecret
  tidak bocor.
- `baseline.json.acquisition` mencatat awal/akhir pembacaan snapshot, pod, dan
  node. `at` adalah awal snapshot, bukan satu instan tunggal; pembacaan
  berurutan dapat memakan waktu dan tidak boleh ditafsirkan sebagai pengukuran
  serentak.
- Node diambil dari API metrics-server mentah
  (`/apis/metrics.k8s.io/v1beta1/nodes`) dan `Node.status.allocatable`, bukan
  `kubectl top nodes` yang dibulatkan. Setiap node menyimpan kuantitas mentah
  (`cpu_usage`, `memory_usage`, `cpu_allocatable`, `memory_allocatable`), nilai
  eksak (`cpu_*_nanocores`, `memory_*_bytes`), `cpu_percent`/`memory_percent`,
  `metrics_timestamp`, `metrics_window`, dan batas akuisisi kedua pembacaan.
  Memori berarti working set metrics-server dibagi allocatable.
- Cakupan node harus sama antara metrics-server dan inventaris `Node`; nama
  duplikat, node hilang/berlebih, kuantitas tidak valid, timestamp/window tidak
  valid, atau penyebut nol/non-positif adalah `InstrumentationError`. Tidak ada
  fallback ke CLI bulat atau MemAvailable host.
- Kebaruan timestamp hanya dicatat, bukan diuji terhadap ambang baru. Protokol
  tidak menetapkan ambang freshness numerik; menambahkannya memerlukan keputusan
  metode terlebih dahulu.

## Keluaran dan bukti

`<out>/<run_id>.jsonl` — satu baris hasil; `<out>/<run_id>.csv` — kolom analisis.
Direktori `<out>/<run_id>/` menyimpan:

| Berkas | Isi |
|---|---|
| `baseline.json` | snapshot baseline tersanitasi, HPA, pod/node, batas akuisisi; `null` bila baseline gagal |
| `readiness.json` | observasi gate baseline yang ditolak: alasan, waktu, batas akuisisi, pod/node/HPA/Argo tanpa resource/Secret |
| `contract.json` | kontrak empat resource dari deklarasi beku: identitas, bidang terpilih, manifest pemulihan tersanitasi, `baseline_sha256`, revisi/render |
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
`r1_baseline`, `r1_first`, `r1_last`, `r1_baseline_details`,
`r1_first_details`, `r1_last_details`, `kubectl_cmds`, `analysis_group`,
`efficacy_eligible`, `source_revision`, `render_sha256`, `baseline_sha256`.

### Keluaran batch

| Berkas | Isi |
|---|---|
| `<batch_id>.manifest.json` | seed, urutan lengan, permutasi skenario, run ID/status/urutan, revisi/render, cooldown/retry, `attempts` per sel, `cooldowns`, hitungan agregat |
| `<batch_id>.rows.jsonl` | seluruh baris attempt dengan metadata batch; `env` tetap lengan mentah |
| `<batch_id>.analysis.jsonl` | baris v2 yang layak analisis, satu baris per sel (attempt terakhir); `env=imperative` dipetakan ke `manual` |
| `<batch_id>.csv` | gabungan kolom CSV historis melalui `convert.py` |
| `<batch_id>.summary.json` | hitungan R1/R2, penyensoran per metrik, daftar eksklusi |

Baris batch menambahkan `batch_id`, `batch_index`, `batch_phase` (`R1`/`R2`),
`batch_attempt`, `batch_retry_of`, `batch_mode`, `batch_stop_reason`,
`stack_isolated: false`, `r3_status: not_measured`, `production_like`, dan
`formal_execution_approved`. Baris mentah `<run_id>.jsonl` dari harness tidak
diubah dan tetap `formal_execution_approved: false`; attestation batch hanya ada
di `<batch_id>.rows.jsonl`, `<batch_id>.analysis.jsonl`, manifest, dan summary.

`analysis.jsonl` hanya memuat run dengan status `observed`/`right_censored`,
postcondition terverifikasi, cleanup/restore sukses, serta status metrik yang
valid untuk `summarize.py`. Untuk sel yang di-retry, hanya attempt terakhir yang
dapat menjadi observasi; attempt baseline yang gagal tetap ada di
`rows.jsonl`/CSV sebagai bukti dan tidak menambah N. Run dry, gagal, tidak
lengkap, atau tanpa bukti tetap ada di `rows.jsonl`/CSV dan dicatat di
`exclusions` summary. A/F tetap terpisah sebagai
`hpa_control`/`visibility_boundary`; keduanya tidak masuk klaim efikasi.

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
menolak subjek non-S1/S2).

### Pemetaan v2 ke analisis batch

| Sumber | Aturan |
|---|---|
| `env` | `rows.jsonl` memakai `imperative`; `analysis.jsonl` dan CSV memetakan ke `manual` karena `summarize.py` hanya menerima `manual`/`gitops` |
| `arm` | tetap nilai mentah (`imperative`/`gitops`), tidak ditimpa |
| `rep` | 1--10 = R2; 11--15 = R1; `batch_phase` mencatat blok |
| Waktu | `detection_seconds`, `evidence_seconds`, `recovery_seconds` dari `t_d/t_e/t_r - t0` monotonik; tidak ada imputasi |
| Penyensoran | `*_status=right_censored`, nilai `null`, `censor_seconds` = batas beku |
| Eksklusi | status gagal, cleanup/restore gagal, postcondition gagal, atau metrik tidak valid tidak masuk `analysis.jsonl`; tetap di `rows.jsonl`/CSV dan `summary.exclusions` |
| Kontrol | A = `hpa_control`, F = `visibility_boundary`; keduanya tidak dipool ke efikasi B--E/G |
| R3 | `r3_status: not_measured`; tidak ada klaim akar masalah atau audit |
| Isolasi | `stack_isolated: false`; satu stack berurutan, bukan dua lingkungan terisolasi |

`summarize.py` dijalankan pada `<batch_id>.analysis.jsonl`, bukan pada baris
mentah yang masih memakai `env=imperative`:

```bash
python3 experiments/analysis/summarize.py --in <out>/<batch_id>.analysis.jsonl
```

Ringkasan batch (`<batch_id>.summary.json`) melaporkan jumlah R1/R2, jumlah run
teramati/tersensor per metrik, daftar eksklusi, dan `analysis_rows`. Median hanya
deskriptif untuk bagian teramati; tidak ada uji inferensial otomatis.

## Batas `--production-like`

Flag ini hanya attestation operator bahwa batch dijalankan pada stack nyata yang
ada, bukan bukti izin formal, bukan pembuatan lingkungan terisolasi, dan bukan
pengukuran R3. Konsekuensinya tetap:

- `stack_isolated: false` — hanya satu stack; tidak ada pasangan A/B terisolasi.
- `r3_status: not_measured` — R3 dikecualikan/ditunda; atribusi pelaku tidak
  dapat dinilai.
- `formal_execution_approved: true` hanya jika `--production-like` diberikan
  bersamaan dengan `--live`; dry-run dengan flag itu ditolak.
- Flag tidak menutup gate seed, kapasitas, NTP, render, atau persetujuan
  pembimbing; R3 tetap `not_measured` dan audit tidak diminta pada gelombang ini.
  Ia juga tidak mengubah run gagal menjadi data yang layak analisis.

Tanpa flag, seluruh baris batch dan manifest tetap `formal_execution_approved:
false`. Jangan menyalin metadata batch ke baris mentah harness atau menganggap
dry-run sebagai observasi.

## Gerbang formal yang belum tertutup

1. **Kesiapan formal satu stack**: stack `invenio` adalah satu-satunya stack
   nyata pada arah desain satu stack berurutan. Ketersediaannya di guard tidak
   otomatis mensertifikasi kesiapan formal; izin, pembekuan, kapasitas, bukti
   seed/recovery yang tersisa, dan bukti pendukung tetap harus ditutup.
2. **Audit API/R3 (dikecualikan)**: R3 tetap `not_measured`; audit API
   dikecualikan/ditunda dan bukan gerbang atau syarat mengaktifkan audit pada
   gelombang ini. Unsur pelaku tetap tidak dapat dinilai.
3. **Seed dan reset**: unggah/unduh seed serta reset/pembersihan orphan telah
   diverifikasi terpisah. Yang masih belum terbukti adalah pemulihan
   database/berkas terisolasi pasca-seed pada stack nyata; verifikasi seed
   harness memakai token dan gagal tertutup, tetapi tidak memulihkan data.
4. **Versi runtime**: ArgoCD, CNPG, OpenSearch, MinIO, dan chart belum dibekukan
   pada revisi yang benar-benar berjalan.
5. **Render, revisi, dan oracle**: `--render-file`,
   `--source-revision`/`--render-sha256` harus berasal dari ekspor render beku
   dan hash byte-nya; loader memvalidasi integritas dan konsistensi revisi,
   tetapi tidak membuktikan provenance render. Catatan pembekuan harus memuat
   perintah/versi persiapan. Harness tidak memperbaiki baseline yang berbeda
   dari deklarasi.
6. **Metode**: tinjauan pemilik/pembimbing untuk lengan imperatif terotomasi,
   kontrol HPA, keluarga uji, dan penanganan data tersensor.
7. **Kapasitas, NTP, SMTP, HA OpenSearch**: bukti jendela beban, sinkronisasi jam,
   relay email, dan HA belum ada; tidak boleh menjadi prasyarat diam-diam.
8. **Pilot 27 Oktober dan percobaan formal yang dihentikan**: pilot terbatas
   27 Oktober 2026 berhasil dan tetap bukti pilot, bukan data formal. Percobaan
   formal yang tidak lengkap dihentikan dan bukan hasil; belum ada run formal
   lengkap yang ditinjau. Tidak ada peluncuran formal baru yang disetujui, dan
   harness belum terbukti siap untuk eksekusi formal.

## Keselamatan dan pengujian

- Dry-run tidak memanggil `subprocess`/HTTP dan tidak memerlukan berkas render;
  live membutuhkan `--live` eksplisit. Batch dry-run memakai jalur harness yang
  sama dan tidak membuat klien Kubernetes.
- Live membaca `--render-file` lokal satu kali, menghitung hash dari byte yang
  di-parse, dan menolak URL, input hilang/duplikat/non-finit, revisi/hash tidak
  cocok, identitas ganda, namespace salah, atau bidang terpilih hilang sebelum
  HTTP/aktivasi lengan/injeksi. Isi berkas tidak dicetak pada error.
- Namespace di luar `invenio`/`exp-*` ditolak; karantina selalu `exp-*`.
- Tidak ada penghapusan seed/record, purge queue, restore, migrasi, atau
  perubahan Secret plaintext.
- Pembersihan karantina dan restore Application berjalan di `finally`;
  kegagalannya dilaporkan dan membuat exit nonzero. Harness hanya menghapus
  namespace karantina yang memiliki label `run-id` milik run ini; namespace
  milik pihak lain tidak disentuh.
- Batch menulis manifest sebelum dan sesudah setiap run. Resume memvalidasi
  skema, identitas run, status, rencana, revisi/render, dan bukti yang sudah ada;
  run terminal tidak pernah dijalankan ulang atau ditimpa.
- Batch berhenti pada kegagalan injeksi/instrumentasi/reset/cleanup/restore dan
  mempertahankan run gagal beserta manifest. Exit nonzero tidak diubah menjadi
  sukses.
- Token hanya dari `INVENIO_TOKEN`, tidak pernah masuk argumen, log, manifest,
  CSV, summary, atau bukti. Error batch di-redaksi bila memuat nilai token.
- Retry hanya menyentuh kegagalan baseline pra-injeksi; cleanup/restore gagal
  tidak pernah di-retry, dan attempt gagal tidak pernah ditimpa.
- `--production-like` bukan bukti izin; `formal_execution_approved` tetap false
  tanpa flag eksplisit, dan `stack_isolated`/`r3_status` tidak berubah.
- `kubectl` dipanggil sebagai argumen list, tanpa shell.

```bash
python3 -m unittest discover -s experiments/tests -v
python3 -m py_compile experiments/live/*.py
bash -n experiments/scripts/*.sh
shellcheck experiments/scripts/*.sh
git diff --check
```
