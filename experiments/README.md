# Instrumen bukti eksperimen (draf untuk tinjauan pemilik)

**Eksperimen formal dan seluruh eksekusi langsung dinonaktifkan.** Empat skrip
adalah entrypoint validasi **offline**, bukan pelaksana injeksi/polling/reset.
Tidak ada klien Kubernetes, eksekusi shell dari input, atau perintah pemulihan
tersembunyi. `--live` gagal nonzero; flag lama yang tidak didukung ditolak.
Kelulusan fixture tidak menyatakan klaster atau aplikasi siap.

## Dua lengan berurutan

Kapasitas terverifikasi hanya satu stack InvenioRDM penuh; lengan imperatif (A) dan
GitOps (B) tidak dijalankan serentak. Satu stack aktif pada satu waktu di namespace
eksperimen yang terpisah dari produksi `invenio`; setiap run dimulai dari seed
bersih, dan reset diverifikasi sebelum run berikutnya. Urutan lengan diacak dan
dicatat; kedua lengan memakai permutasi skenario yang sama.
Lengan A adalah prosedur imperatif terotomasi tetap: pemeriksa dan runbook
berjalan otomatis tanpa waktu reaksi manusia. Evaluator bersama mengukur R1;
kolektor pasif merekam kedua lengan. Rincian protokol ada di
[LIVE-OBSERVER.md](LIVE-OBSERVER.md); dokumen itu rencana, bukan prosedur yang
telah diuji.

## Menjalankan tanpa instalasi atau akses klaster

Memerlukan Python 3.9+ stdlib dan Bash 3.2+ yang telah terpasang.

```bash
python3 -m unittest discover -s experiments/tests -v
bash -n experiments/scripts/*.sh
shellcheck experiments/scripts/*.sh
bash experiments/scripts/baseline-check.sh --evidence experiments/tests/fixtures/complete.json
bash experiments/scripts/metrics-collect.sh --evidence experiments/tests/fixtures/complete.json
bash experiments/scripts/recovery-runbook.sh --evidence experiments/tests/fixtures/complete.json
bash experiments/scripts/drift-inject.sh --evidence experiments/tests/fixtures/complete.json
```

### Adapter akuisisi read-only (belum siap eksperimen)

`acquire-readonly.py --input FILE` memproses bundel API tersimpan tanpa menjalankan
`kubectl`. Bundel input wajib memuat `run_id`, atau berikan `--run-id`; nilai yang
berbeda ditolak. `--read-only --contract FILE --run-id RUN` memakai empat panggilan
baca tetap (nodes, metrics mentah, pods namespace, dan deployments/services/HPA
namespace), tanpa `Secret`/`ConfigMap`, shell, atau perintah dari input. Keluarannya
adalah fragmen observasi bertanda `readiness_verified: false` dan membawa `run_id`;
setiap sampel lengkap yang dibangun dari fragmen itu wajib memakai `run_id` yang
sama. Fragmen ini tidak menulis file, tidak membuat baseline lulus, dan tidak
membuktikan revisi deployment. Panggilan langsung hanya dilakukan atas permintaan
eksplisit pada klaster yang diizinkan. Ini bukan adapter polling/injeksi/reset dan
tidak dijalankan oleh uji.

Fixture bernilai sintetis; semua hasilnya adalah replay, bukan observasi klaster.
Output JSON tunggal ke stdout; kegagalan bukti ke stderr dan exit nonzero. Simpan
hasil baru terpisah dari CSV/hasil historis. Tidak ada konversi otomatis ke format
lama yang memakai `trci` atau menyamakan cap waktu epoch dengan durasi.

## Kontrak bukti

Contoh lengkap: `tests/fixtures/complete.json`. Produsen bukti masa depan harus
berjalan sebelum injeksi, merekam waktu monotonik dalam detik dari satu jam
kolektor, UTC untuk audit, dan mengikat setiap artefak pada run/revisi/render yang
sama. Nilai di kontrak adalah ekspor hasil render yang dibekukan, bukan manifest
editable baru; verifikasi asal ekspor dan sanitasi tetap tanggung jawab produsen
serta peninjau. Evaluator tidak membuktikan autentisitas file JSON.

| Bagian | Kontrak |
|---|---|
| `contract` | Revisi Git 40 heksadesimal, SHA-256 hasil render, inventaris node/pod/sumber daya tidak kosong dan unik, bidang terpilih per identitas |
| `baseline`, `reset` | Snapshot lengkap: revisi/render sama, seluruh bidang cocok, pod Running **dan Ready**, semua node CPU/memori **<70%**, inventaris lengkap, tidak ada objek ekstra/karantina |
| `checks` | Bukti prasyarat audit, SMTP, pemulihan aplikasi, sinkronisasi jam, isolasi, HPA, lifecycle, jendela beban tenang, adopsi runtime, queue, dan data; tidak boleh diasumsikan benar |
| `injection` | Satu permintaan, waktu kirim/ack, keberhasilan API **dan** verifikasi perubahan; `effect` `value_changed`/`deleted`/`created`; gagal/tidak diketahui bukan deteksi nol |
| `events` | Sinyal deteksi pengendali yang benar dan bukti deviasi terpisah, id run/objek/bidang serta referensi artefak tersanitasi; bukan status health atau klaim akar masalah |
| `samples` | Pengamatan berurutan dengan waktu aktual dan bidang yang sama di kedua lengan; setiap sampel wajib memiliki `run_id` yang sama dengan evidence run (hilang/asing ditolak); kegagalan pembacaan bukan nilai default; D/F memerlukan bukti keberadaan pada pengamatan pertama |
| `stop_reason` | `timeout` harus menutup batas beku; `recovery` berhenti lebih awal hanya jika pemulihan dua pengamatan terkonfirmasi |
| `recovery.commands` | Hasil tiap tindakan korektif terukur dengan waktu mulai/akhir di dalam `[injection.started, observation_end]` dan exit code; satu kegagalan menggagalkan verifikasi. Tindakan reset setelah jendela pengamatan bukan bukti waktu pemulihan dan tidak boleh dimasukkan ke field ini |

Setiap event dan sampel harus terikat pada `run_id` evidence yang sama; nilai
hilang atau asing ditolak, bukan dianggap sebagai observasi run ini. Waktu
pemulihan hanya dihitung dari sampel yang valid. Tindakan reset yang terjadi setelah
`observation_end` adalah bukti postcondition terpisah, bukan tindakan koreksi
terukur; jangan memasukkannya ke `recovery.commands` untuk “memperbaiki” waktu
pemulihan.

R1 menghitung persentase **sumber daya yang seluruh bidang terpilihnya cocok**,
dengan penyebut inventaris yang sama. Image, resource requests/limits, ConfigMap,
Secret, keberadaan dan bidang Service yang relevan harus masuk kontrak formal
hasil render. Health/Synced bukan skor R1. Pembacaan lengkap yang menemukan objek
hilang memberi ketidakcocokan; field yang tidak diperiksa atau API gagal memberi
kegagalan instrumentasi. Secret hanya boleh masuk sebagai boolean hasil kesetaraan
di memori; jangan simpan nilai atau hash yang memudahkan tebakan.

Memori menggunakan working set metrics-server / allocatable node, bukan metric
host yang dipilih setelah melihat hasil. Sampel tunggal lolos bukan bukti jendela
stabil: gerbang `quiet_window` harus didukung rangkaian pengamatan sebelum formal.
Tidak adanya metrik/inventaris/bukti resource menyebabkan kegagalan tertutup.

## Kepemilikan dan waktu

- A: lengan imperatif. Pemeriksa dan runbook otomatis; tidak ada operator yang
  menunggu atau mengetik. HPA tetap aktif di **kedua** lengan. `/spec/replicas`
  tidak dinilai sebagai nilai statis Git. Pemulihan dinamis HPA memerlukan bukti
  tersendiri, bukan R1=100. Kelompok `hpa_control` tidak layak untuk klaim efikasi
  ArgoCD.
- B--E/G: sinyal dari pemeriksa imperatif (A) atau ArgoCD (B) sesuai lengan; bukti
  deviasi mengidentifikasi bidang, bukan menyimpulkan penyebab kausal.
- F: batas visibilitas objek tak terkelola, dilaporkan terpisah; tidak dijanjikan
  terdeteksi atau dipangkas ArgoCD. Pemulihan mensyaratkan objek ekstra tidak ada.
- Recovery: dua pengamatan cocok berurutan, waktu pertama dilaporkan. Adopsi
  runtime, kesiapan layanan, queue/data dan reset lengkap diperiksa terpisah.
- Tidak teramati sampai batas pengamatan: `*_seconds: null`, status
  `right_censored`, serta durasi batas. Berhenti lebih awal karena pemulihan tetapi
  sinyal tidak teramati memberi `unobserved_before_stop`, bukan sensor dan bukan nol.
  Kegagalan API/format/penerimaan injeksi memberi status kegagalan, bukan sensor.

Tidak ada field akar masalah manusia. R2 v2 memakai `t_d`, `t_e`, dan `t_r`; semua
waktu berasal dari jam monotonik kolektor. Mekanisme koreksi berjalan otomatis
dan tidak menerima label skenario.

## Sumber deployment dan kesiapan

[`deployment-source.json`](deployment-source.json) hanya menunjuk sumber
otoritatif pada revisi yang diperiksa. Snapshot 25 Oktober 2026 mencatat tiga
node RKE2 Ready, Kubernetes v1.32.6+rke2r1, Ubuntu 24.04 LTS, 18/18 Application
ArgoCD Synced/Healthy, satu namespace aplikasi `invenio` tanpa namespace kembar,
dan satu stack InvenioRDM penuh. Sampel memori 59% pada kedua worker bukan bukti
jendela stabil atau penempatan dua stack. Versi ArgoCD, CNPG, OpenSearch dan
MinIO tidak dicatat dalam snapshot; rekam versi/revisi runtime aktual sebelum
formal. Snapshot lingkungan diverifikasi terhadap `main` di `d7ef120`, sedangkan
sumber deployment yang diperiksa adalah `6cacea66`. Referensi kode rekonsiliasi
menetapkan 30s, berbeda dari target proposal lama 60s. Jangan menyamakan interval
repository reconciliation, self-heal retry, event watch dan interval evaluator.

Bloker tetap terbuka: kapasitas hanya satu stack, sehingga dua lengan harus
berurutan; bukti penempatan dua stack tidak ada, audit belum tersedia, SMTP masih
placeholder, OpenSearch HA ditunda, dan private-draft seed serta recovery/reset
aplikasi belum diverifikasi. Tidak ada izin purge queue/data, restore, deploy,
migrasi atau injeksi dari dokumen ini.

Adapter akuisisi langsung, ekspor render yang aman, bootstrap terpisah dari repair,
dan verifikasi reset aplikasi harus ditinjau/diintegrasikan sebelum izin eksperimen.
Antarmuka lifecycle lintas-repo perlu menyediakan revisi sumber dan digest render,
inventaris/bidang eksplisit, kepemilikan pengendali, identitas serta waktu tindakan,
exit code, dan postcondition; kegagalan wajib diteruskan ke pemanggil.
