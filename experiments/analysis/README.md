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
