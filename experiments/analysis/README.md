# Analisis bukti dan reproduksi historis

## Bukti v2 aktif

`metrics-collect.sh --evidence FILE` menghasilkan JSON v2, bukan CSV lama.
Simpan satu hasil per baris ke file baru (jangan menimpa artefak historis), lalu:

```bash
python3 experiments/analysis/summarize.py --in /path/hasil-v2.jsonl
```

Ringkasan stdlib memisahkan skenario, lengan, kelompok analisis, data sintetis,
revisi sumber dan digest render. A tetap `hpa_control`, F `visibility_boundary`,
B--E/G `managed_drift`; tidak ada pooling kontrol ke efikasi ArgoCD. Untuk setiap
metrik, jumlah teramati dan tersensor tetap dilaporkan. Median hanya untuk bagian
teramati dan **bukan** estimasi yang sudah disesuaikan terhadap penyensoran.
Tidak ada uji inferensial otomatis sebelum metode/keluarga uji disetujui.

Kegagalan injeksi, instrumentasi dan reset disimpan pada ledger run tersendiri
dengan alasan serta referensi bukti; jangan membuangnya untuk membentuk dataset
yang hanya berisi sukses. Evaluator mengembalikan exit nonzero pada bukti tidak
valid, bukan mengarang observasi atau menulis hasil sukses.

## Batch live

`experiments/live/run_matrix.py` menulis `<batch_id>.analysis.jsonl` yang sudah
memetakan `env=imperative` ke `manual` dan hanya memuat baris yang lolos
validasi metrik, postcondition, cleanup, dan restore. Umpan file itu ke
`summarize.py`; baris mentah `<batch_id>.rows.jsonl` tetap memakai lengan asli
dan seluruh kegagalan. Ringkasan batch (`<batch_id>.summary.json`) memisahkan
R1/R2, hitungan tersensor, dan eksklusi. Lihat `experiments/live/README.md`
untuk batas `stack_isolated: false`, `r3_status: not_measured`, dan
`formal_execution_approved`.

### Analisis inferensial batch live

`summarize.py` tetap deskriptif. `analyze_live.py` menerapkan keluarga uji yang
dibekukan pada Bab III terhadap `<batch_id>.analysis.jsonl`. `--rows` opsional
menambahkan hitungan eksklusi dari `<batch_id>.rows.jsonl`; tanpa berkas itu,
eksklusi dilaporkan sebagai tidak dihitung, bukan nol.

```bash
python3 experiments/analysis/analyze_live.py \
  --in experiments/live/runs/formal-<batch-id>/<batch-id>.analysis.jsonl \
  --rows experiments/live/runs/formal-<batch-id>/<batch-id>.rows.jsonl \
  --out experiments/analysis/outputs/<batch-id>
```

Keluaran yang sudah ada ditolak kecuali `--force` diberikan. Bootstrap bersifat
deterministik: `--bootstrap 2000` (minimum 100), `--seed 20261027`, dan
`--alpha 0.05` dapat diubah, tetapi nilai baku itulah yang harus dicatat untuk
reproduksi. Tanpa `--rows`, eksklusi tidak dapat dihitung; `rows.jsonl` hanya
memuat run yang tercatat, sehingga run `not_run` tetap berada di manifest dan
summary, dan tidak dihitung sebagai eksklusi di sini.

| Berkas | Isi |
|---|---|
| `live_analysis.json` | hasil lengkap: populasi, eksklusi, R1, survival, uji, efek, keluarga Holm |
| `live_overview.tex` | jumlah baris R2, run teramati/tersensor, populasi, eksklusi, `R3: not measured` |
| `live_exclusions.tex` | baris yang dieksklusi beserta alasan |
| `live_r1.tex` | median baseline/first/last per skenario, lengan, fase; jumlah observasi |
| `live_survival.tex` | Kaplan--Meier, median, RMST, jumlah event/tersensor, horizon |
| `live_tests.tex` | Wilcoxon berpasangan atau Mann--Whitney eksploratif, $p$ mentah dan Holm |
| `live_effects.tex` | Cliff's $\delta$, selisih median berpasangan, rank-biserial, CI bootstrap |

Cara membaca hasil:

- **Populasi.** Hanya B--E yang masuk efikasi *managed drift*. A tetap kontrol
  HPA, F batas visibilitas, dan G deskriptif non-Argo. Ketiganya muncul di
  tabel survival/overview tetapi tidak pernah dipool ke uji B--E. Baris batch
  memberi G `efficacy_eligible: true` karena aturan runner hanya mengecualikan
  A/F; analyzer menimpanya menjadi deskriptif non-Argo sesuai metode beku.
- **Pemilihan uji.** Wilcoxon *signed-rank* dipakai hanya bila setiap blok
  skenario-replikasi memiliki kedua lengan dan kedua nilai teramati; blok yang
  tersensor atau tanpa pasangan memaksa Mann--Whitney U. Alasan tercatat di
  `pairing.reason` dan penanda P/U pada tabel uji, bukan dipilih berdasarkan
  hasil. Wilcoxon
  memakai $p$ eksak *sign-flip* untuk maksimal 16 pasangan dan mengabaikan
  selisih nol. Uji Mann--Whitney hanya memakai nilai teramati, memakai
  aproksimasi normal dengan koreksi *ties*, dan **tidak** menyesuaikan
  penyensoran. Kedua uji adalah analisis *complete-case*/teramati, bukan
  estimasi yang sudah dikoreksi penyensoran.
- **Holm.** Keluarga yang ditetapkan sebelum data berisi 12 hipotesis
  B--E $\times$ \{deteksi, bukti, pemulihan\}. Hipotesis yang tidak terestimasi
  diperlakukan sebagai $p=1$ sehingga koreksi bersifat konservatif. Nilai
  `reject_holm` bukan klaim konfirmatoris.
- **Penyensoran.** Waktu tersensor tidak pernah diisi nol. Kaplan--Meier dan
  RMST memakai horizon batas penyensoran terkecil per kelompok; median `--`
  berarti tidak tercapai dalam horizon. RMST adalah deskripsi hingga horizon,
  bukan uji superioritas.
- **R1.** Baseline/first/last dilaporkan sebagai median bagian teramati dengan
  jumlah observasi; nilai hilang tidak diimputasi. R1 tidak diuji.
- **Klaim.** `claim_status` selalu `exploratory_case_study` dan
  `confirmatory_claims` selalu `false`. `formal_execution_approved: true` hanya
  attestation operator, bukan persetujuan metode atau bukti bahwa seluruh
  gerbang formal tertutup.
- **R3.** `R3: not measured`; tidak ada klaim audit atau keterlacakan.

Input divalidasi secara *fail-closed*: skema, pemetaan lengan, fase/rep,
revisi/render, status metrik, dan nilai tersensor yang tidak konsisten
ditolak. Batas penyensoran divalidasi per baris; horizon RMST adalah batas
terkecil per kelompok. Ketidakcocokan `rows.jsonl` dengan `analysis.jsonl` juga
ditolak agar tidak ada baris yang hilang diam-diam. Analisis tidak mencetak
nilai baris mentah; hanya metadata yang diizinkan yang masuk artefak eksklusi.

### Identitas retry

`analysis.jsonl` memakai attempt terakhir tiap sel, sehingga satu sel tetap satu
observasi. Run ID retry dari runner berbentuk
`<batch>-<lengan>-<skenario>-r<rep>-retry<N>`. Analyzer menerima ID dasar tanpa
metadata attempt (bukti lama) dan ID retry hanya bila `batch_attempt` adalah
bilangan bulat >= 1 yang sama dengan `<N>` dan `batch_retry_of` sama dengan ID
dasar. Metadata parsial, nilai boolean/float/negatif/string, parent berbeda,
sufiks tidak kanonik (`retry0`, `retry01`, `retryx`), dan sel ganda (basis plus
retry di `analysis.jsonl`) ditolak. ID asli tidak diubah dan attempt gagal tidak
menambah observasi statistik.

Dengan `--rows`, setiap baris mentah divalidasi terhadap batch, lengan,
skenario, replikasi, dan metadata attempt yang sama. Untuk run yang masuk
`analysis.jsonl`, proyeksi field protokol/provenans/metrik yang tersedia harus
sama dengan baris analysis (fase, mode, revisi, render, batas sensor,
kelompok, eligibility, synthetic, attestation, R1, dan metrik); `env`
dinormalisasi dari `imperative` ke `manual`. Baris tersebut juga tidak boleh
membawa cleanup/arm restore/postcondition gagal atau stop/error eksplisit.
Rantai attempt per sel harus berurutan dari 0; setiap attempt > 0 harus
didahului `baseline_failure` yang memenuhi kebijakan retry runner: tanpa `t0`,
injeksi tidak diterima, cleanup `ok`, arm `restored`, dan tanpa mutasi.
Attempt baseline gagal tetap muncul di tabel eksklusi sebagai bukti, bukan
observasi tambahan. Field eligibility lama yang tidak ada tidak diminta, tetapi
nilai yang ada dan tidak valid tetap ditolak; validasi ini tidak mengklaim
verifikasi bukti lengkap. Tanpa `--rows`, hubungan rantai tidak dapat
diverifikasi; analyzer hanya memeriksa konsistensi metadata di
`analysis.jsonl` dan tidak mengklaim validasi rantai. Baris lama tanpa field
attempt diperlakukan sebagai attempt 0.

## Artefak historis, bukan hasil Invenio

`outputs/`, `mockgen.py`, `runs/sample-dryrun.csv` dan format CSV v1 tetap
dipertahankan untuk sejarah/reproduksi. Angka `trci` sintetis di sana tidak menjadi
waktu akar masalah nyata. S1/S2 tidak digabungkan ke inferensi formal. R1 v1
berupa pecahan dan semantik waktu v1 berbeda dari v2 (persen dan durasi monotonik).
Jangan mengganti mock dengan data nyata lalu menjalankan analyzer lama.

Protokol v2 tidak memakai field akar masalah manusia; R2 memakai `t_d`, `t_e`, dan
`t_r` dari kolektor. `trci` pada CSV historis tetap artefak lama dan tidak
disamakan dengan metrik v2.

Jika dependensi historis sudah terpasang, reproduksi hanya ke direktori baru:

```bash
python3 experiments/analysis/analyze.py --historical-mock-only \
  --in experiments/analysis/outputs/mock_runs.csv --out /path/output-historis-baru
```

Mode ini menolak input tanpa label `mock seed=` dan subjek S1/S2. Hasilnya tetap
perbandingan sintetis historis, tidak mengikuti estimand HPA/Invenio yang baru.
Tidak perlu instalasi atau unduhan untuk pengujian instrumen v2.
