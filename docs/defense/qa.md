# Defense Q&A — ringkas dan dapat dilacak

Dokumen ini adalah alat latihan sidang, bukan bagian dari naskah skripsi. Setiap
jawaban menunjuk ke Bab/tabel atau ke artefak reproduksi. Angka hasil berasal
dari `experiments/analysis-formal-20261029/live_analysis.json` dan
`experiments/formal-20261029/formal-20261029.summary.json`.

Catatan istilah: label `R1`/`R2` adalah nama fase data internal pada keluaran
analisis. Naskah tidak memakai label itu sebagai metrik; naskah memakai
"pemeriksaan kecocokan konfigurasi" dan "blok waktu / blok kecocokan".

## 1. Mengapa 210 sel, 211 baris mentah, dan 207 baris analisis?

210 sel adalah rencana 7 skenario × 2 mode × 15 pengulangan. Ada 211 baris
mentah karena satu sel, `gitops-C-r08`, gagal pada baseline pra-injeksi dan
diulang satu kali. Analisis menerima 207 baris dan mengecualikan empat baris
mentah; tiga sel tidak menghasilkan baris analisis, sedangkan `C-r08` tetap
dianalisis melalui `-retry1`. Lihat Bab IV Tabel 4.1 dan `experiments/DATA.md`.

## 2. Mengapa kesehatan layanan bukan hasil komparatif?

Kesehatan layanan adalah pemeriksaan pengaman sebelum injeksi dan pemeriksaan
setelah pemulihan. Status Running/Ready tidak diskor, tidak dibandingkan
antarmode, dan tidak masuk skor kecocokan konfigurasi. Menggabungkannya ke skor
akan mencampur kesetaraan field dengan kesehatan layanan. Lihat Bab I
§Rumusan Masalah, Bab III §Pemeriksaan Kecocokan Konfigurasi, dan Bab IV
§Data yang Dianalisis.

## 3. Mengapa mode imperatif bukan baseline manusia?

Mode imperatif adalah runbook dan checker `kubectl` otomatis yang tetap. Ia
bekerja pada tingkat prosedur, bukan kecepatan operator manusia. Istilah
"prosedur manual" hanya bertahan sebagai sejarah proposal; naskah memakai
"prosedur imperatif otomatis" pada sebutan pertama lalu "mode imperatif".
Karena prosedurnya otomatis dan konservatif, keunggulan waktu GitOps tidak dapat
dijelaskan oleh kelambatan manusia. Waktu reaksi manusia tidak diukur. Lihat
Bab I dan Bab III.

## 4. Mengapa hanya satu stack dan dua mode berurutan?

Kapasitas yang tersedia hanya satu stack InvenioRDM penuh. Dua stack paralel
akan menggandakan kebutuhan dan mengubah validitas ekologis. Konsekuensinya,
perlakuan tidak terisolasi dari beban latar, dependensi bersama, dan efek
periode; ini keterbatasan yang dinyatakan, bukan efek yang diabaikan. Lihat
Bab III dan Bab V.

## 5. Mengapa urutan mode tetap dan tidak diacak ulang?

Urutan mode diundi satu kali dengan angka acak untuk urutan sebelum koleksi:
GitOps lalu imperatif. Urutan skenario yang terwujud adalah E, A, G, D, C, F, B.
Pengulangan berjalan berurutan dan tidak diacak ulang per blok. Karena urutan
mode tetap, efek periode tidak dapat dipisahkan sepenuhnya dari efek mode.
Pengulangan berbagi satu stack dan satu periode, sehingga pengulangan tidak
sepenuhnya independen dan nilai p adalah ringkasan deskriptif, bukan estimasi
kausal atau estimasi populasi. Lihat Bab III §Rancangan Perbandingan dan Bab IV
§Dapatkah Hasil Ini Dipercaya.

## 6. Mengapa satu pertanyaan penelitian dengan dua metrik?

Pertanyaan penelitian membandingkan waktu deteksi dan waktu pemulihan. Keduanya
proses berbeda: deteksi menandai ketidakcocokan, pemulihan membawa seluruh field
kembali cocok. Waktu tersedianya bukti dicatat sebagai diagnostik: pada mode
imperatif `t_e = t_d` menurut konstruksi, sedangkan pada GitOps `t_e` berasal
dari kolektor independen. Karena itu `t_e` tidak dibandingkan sebagai keunggulan
antarmode. Lihat Bab I §Rumusan Masalah, Bab II §Mengapa Deteksi dan Pemulihan
Dipisahkan, dan Bab III §Waktu Deteksi, Bukti, dan Pemulihan.

## 7. Mengapa selisih deteksi 4,2–4,3 detik?

Pemeriksa imperatif membaca keadaan setiap 5 detik, sedangkan pencatat membaca
setiap 1 detik. Selisih maksimum yang diharapkan dari kedua selang itu sekitar
4 detik; selisih teramati sedikit di atasnya tetapi mendekati batas itu.
Karena mode dan selang pengamatan berubah bersama, data ini tidak dapat
memisahkan kecepatan respons pengendali dari selang pengamatan. Temuan yang
dapat dipertahankan adalah bahwa deteksi dibatasi oleh seberapa sering keadaan
dibaca, bukan bahwa GitOps secara inheren lebih cepat. Lihat Bab IV §Waktu
Deteksi dan Bab V §Temuan Utama.

## 8. Mengapa pemulihan B tidak disebut keunggulan yang jelas?

Ukuran efek pemulihan B adalah 0,48 dengan interval kepercayaan yang mencakup
nol. C adalah 0,75, D 1,00, dan E 0,86. Pada D selisihnya paling besar; pada E
arahnya lebih konsisten daripada B. Karena itu pemulihan tidak dibaca sebagai
satu keunggulan seragam. Lihat Bab IV §Waktu Pemulihan dan Lampiran B
Tabel B.3–B.4.

## 9. Apakah G membuktikan ArgoCD gagal atau masalah izin?

Tidak. G menunjukkan anotasi SealedSecret tidak kembali ke desired state dalam
300 detik pada mode GitOps. Mekanisme yang paling mungkin adalah cakupan diff
dan client-side apply, tetapi mekanisme itu tidak diukur. Status formalnya
`unattributed`; tidak ada bukti masalah izin. G adalah kasus batas deskriptif,
bukan uji self-heal ArgoCD. Lihat Bab IV §Kasus G.

## 10. Mengapa pemeriksaan kecocokan konfigurasi bukan hasil komparatif?

Pemeriksaan itu memastikan manipulasi bekerja: skor 100 berarti keempat sumber
daya terpilih cocok dengan deklarasi, dan satu ketidakcocokan menghasilkan 75.
Pemeriksa dan evaluator memakai kontrak yang sama, sehingga B–F harus kembali
ke 100 bila prosedur bekerja. Tabel audit ada di Lampiran A dan tidak diuji
antarmode. Lihat Bab III §Pemeriksaan Kecocokan Konfigurasi dan Lampiran A
§Audit Pemeriksaan Kecocokan Konfigurasi.

## 11. Mengapa ada keluarga 12 perbandingan dan koreksi Holm?

Keluarga uji ditetapkan sebelum koleksi: empat skenario efikasi B–E × tiga
metrik waktu (deteksi, bukti, pemulihan) = 12. Holm mengendalikan family-wise
error pada keluarga itu. A, F, dan G tidak ditambahkan ke keluarga. Di naskah,
angka p dan nama uji ditempatkan di Lampiran B; Bab IV hanya memakai median.
Lihat Bab III §Analisis Data dan Lampiran B.

## 12. Mengapa C dan D memakai Mann–Whitney?

Wilcoxon hanya dipakai bila setiap blok skenario–replikasi memiliki kedua mode
dan kedua nilai teramati. Pada C, pasangan lengkap tidak terbentuk; pada D
deteksi dan bukti juga tidak. Aturan fallback ditetapkan sebelum analisis,
bukan dipilih setelah melihat hasil. Lihat Lampiran B Tabel B.2.

## 13. Mengapa ada 15 kejadian pemulihan yang berhenti sebelum peristiwa?

Sepuluh terjadi pada blok waktu dan lima pada blok kecocokan; seluruhnya berasal
dari mode GitOps pada skenario G. Observasi tersebut tidak mencapai titik akhir
dalam horizon 300 detik, jadi dilaporkan berhenti sebelum peristiwa, bukan
kegagalan instrumen dan bukan nilai nol. Tidak ada imputasi. Lihat Bab IV
§Kasus G dan Lampiran B §Pengamatan yang Berhenti Sebelum Peristiwa dan
Analisis Kelangsungan Hidup.

## 14. Mengapa ada empat baris dengan `t_e < t_d`? Apakah waktunya negatif?

Tidak. `t_d` dan `t_e` berasal dari dua jalur pengamatan yang berbeda; evaluasi
bukti dapat selesai sebelum sinyal deteksi terbaca. Selisih bertanda dilaporkan
apa adanya, tidak dibulatkan menjadi nol. Empat baris itu semuanya GitOps:
B-r02, B-r06, C-r04, E-r04. Lihat Bab III §Waktu Deteksi, Bukti, dan Pemulihan
dan Lampiran B §Rumus dan Definisi Teknis.

## 15. Apa yang tidak dibuktikan oleh kesetaraan konfigurasi?

Kesetaraan tidak membuktikan kebenaran semantik, keamanan, atau kualitas
deklarasi. Kedua mode dapat mencapai kondisi identik dan sama-sama salah bila
deklarasi sumbernya keliru. Pemeriksaan kecocokan juga tidak menilai kesehatan
layanan secara umum. Lihat Bab V §Keterbatasan.

## 16. Mengapa R3 tidak diukur?

R3 (traceability/audit API) membutuhkan audit log API server yang tidak tersedia
pada apparatus ini. R3 dilaporkan sebagai `not_measured` dan menjadi pekerjaan
lanjutan, bukan hasil. Lihat Bab V §Keterbatasan.

## 17. Apakah biaya sudah diukur?

Belum. Penelitian ini tidak mengukur biaya kontrol, penyimpanan, atau jam orang.
Bab V §Biaya dan Overhead memuat daftar metrik yang perlu diukur, bukan angka
atau perkiraan harga. Rekomendasi adopsi karena itu hanya mencakup waktu, bukan
total biaya kepemilikan. Lihat Bab V §Biaya dan Overhead.

## 18. Apakah kolaborasi, waktu tinjauan, audit, dan kepemilikan insiden diukur?

Tidak. Aspek-aspek itu mungkin membaik dengan GitOps, tetapi penelitian ini
hanya mengukur waktu deteksi, waktu pemulihan, dan kecocokan field. Bab V
§Aspek yang Tidak Diukur menyarankan studi kualitatif atau campuran untuk
mengukurnya. Jangan menyajikan aspek itu sebagai temuan. Lihat Bab V.

## 19. Apa satu kalimat yang harus diingat penguji?

Pada apparatus, protokol, dan cakupan field yang diuji, waktu deteksi mengikuti
selang pengamatan (1 detik versus 5 detik), pemulihan tidak seragam (B/C lebih
kecil, D paling besar), dan G adalah pengecualian deskriptif yang tidak
diatribusikan.

## 20. Apakah refactor kode setelah koleksi membatalkan hasil?

Tidak. Apparatus koleksi ditetapkan pada `3572f3c`; kode `HEAD` bukan revisi
koleksi. Refactor pasca-koleksi diuji dengan 502 tes inti + 9 tes sensitivity,
keluaran analisis yang ditetapkan identik, dan dry-run 210 sel. Untuk mengaudit
angka, gunakan keluaran yang ditetapkan dan data mentah, bukan menjalankan ulang
batch. Lihat `experiments/REVISIONS.md`.

## 5-minute code walkthrough

Use this order when an examiner asks to see the apparatus. Timings are targets,
not claims; stop at the collection boundary.

| Time | Show | Say |
|---|---|---|
| 0:00 | `git rev-parse 'thesis-collection-20261029^{commit}'` and `'thesis-analysis-20261030^{commit}'` | Collection and analysis are separate; `HEAD` is post-collection. |
| 0:40 | `experiments/live/harness.py` (`build_contract`, `score`, baseline gate) | The contract is fixed; score 100 is the recovery predicate. |
| 1:40 | `experiments/live/harness.py` timing endpoints and `experiments/live/sampling.py` | `t_d`, `t_e`, `t_r` come from completed observations; no imputation; 5 s checker versus 1 s recorder. |
| 2:30 | `experiments/analysis/analyze_live.py` (`analyze`, `_r1_entries`, `_comparison`, `holm_adjust`) | The analyzer selects B–E, applies the fixed fallback rule, and keeps the configuration check descriptive. |
| 3:30 | `experiments/analysis/rq2_report.py` and `docs/defense/source-map.md` | The thesis view selects the timing fields, derives `t_r - t_d`, and maps the historical `env=manual` alias to `arm=imperative` while preserving `legacy_env=manual`. |
| 4:30 | `experiments/formal-20261029/PROVENANCE.json` and `experiments/DATA.md` | Raw rows and analysis outputs are local; the checkout documents and tests the code, not a recomputation of observed numbers. |

Never edit the analyzer or the collection modules during a walkthrough.
If a live rerun is requested, stop: a new batch needs new approval, a new
identity, and a new apparatus freeze.
