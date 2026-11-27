# Defense Q&A — ringkas dan dapat dilacak

Dokumen ini adalah alat latihan sidang, bukan bagian dari naskah skripsi. Setiap
jawaban menunjuk ke Bab/tabel atau ke artefak reproduksi. Angka hasil berasal
dari `experiments/analysis-formal-20261029/live_analysis.json`,
`experiments/formal-20261029/formal-20261029.summary.json`, dan
`experiments/analysis-matched1s-20261127b/live_analysis.json` untuk tindak
lanjut selang 1 detik. Pertanyaan 1–20 membahas batch utama `formal-20261029`;
pertanyaan 21–22 membahas tindak lanjut `matched1s-20261127b`.

Catatan istilah: kode dan keluaran beku masih memakai nama field internal serta
alias historis `env=manual`. Nama itu adalah nama teknis, bukan metrik naskah.
Naskah dan deck memakai "pemeriksaan kecocokan konfigurasi" serta "blok waktu /
blok kecocokan".

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
Karena prosedurnya otomatis dan konservatif, perbedaan waktu yang menguntungkan
GitOps tidak dapat dijelaskan oleh kelambatan manusia. Waktu reaksi manusia
tidak diukur. Lihat Bab I dan Bab III.

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
dari kolektor independen. Karena itu `t_e` tidak dibandingkan sebagai perbedaan
yang menguntungkan salah satu mode. Lihat Bab I §Rumusan Masalah, Bab II §Mengapa
Deteksi dan Pemulihan Dipisahkan, dan Bab III §Waktu Deteksi, Bukti, dan
Pemulihan.

## 7. Mengapa selisih deteksi 4,2–4,3 detik?

Pemeriksa imperatif membaca keadaan setiap 5 detik, sedangkan pencatat membaca
setiap 1 detik. Jadwal pengamatan saja dapat menghasilkan selisih hampir 5
detik; selisih teramati 4,2–4,3 detik konsisten dengan kedua selang itu.
Karena mode dan selang pengamatan berubah bersama, data ini tidak dapat
memisahkan kecepatan respons pengendali dari selang pengamatan. Temuan yang
dapat dipertahankan adalah bahwa deteksi dibatasi oleh seberapa sering keadaan
dibaca, bukan bahwa GitOps secara inheren lebih cepat. Uji tindak lanjut dengan
pemeriksa 1 detik menurunkan selisih menjadi 0,25–0,32 detik; lihat pertanyaan
21. Lihat Bab IV §Waktu Deteksi dan Bab V §Temuan Utama.

## 8. Mengapa pemulihan B tidak disebut perbedaan yang jelas?

Pemulihan tidak seragam. Selisih median paling besar pada D, yaitu 5,08 detik.
Pada B, C, dan E selisihnya sekitar 3 detik: 2,98; 2,99; dan 3,03 detik. Pada B,
ukuran efek 0,48 dengan interval kepercayaan 95% [−0,08; 1,00] yang mencakup
nol, sehingga selisihnya tidak dibaca sebagai perbedaan yang jelas. Pada C,
ukuran efek 0,75 melemah menjadi 0,64 ketika satu percobaan yang dikecualikan
disertakan; arahnya tetap positif tetapi tidak stabil. Pada E, ukuran efek 0,86
lebih konsisten daripada B, tetapi bukan 5 detik seperti D. Jangan menggabungkan
E dengan D. Lihat Bab IV §Waktu Pemulihan dan Lampiran B Tabel B.3–B.4.

## 9. Apakah G membuktikan ArgoCD gagal atau masalah izin?

Tidak. G menunjukkan anotasi SealedSecret tidak kembali ke desired state dalam
300 detik pada mode GitOps; skor kecocokan tetap 75 dan 15 pengamatan berhenti
sebelum peristiwa. Mekanisme yang paling mungkin adalah cakupan diff dan
client-side apply, tetapi mekanisme itu tidak diukur. Status formalnya
`unattributed`; tidak ada bukti masalah izin. Pelajaran praktisnya adalah
cakupan field: rekonsiliasi hanya menegakkan field yang benar-benar dikelola
pengendali. G adalah kasus batas deskriptif, bukan uji self-heal ArgoCD. Lihat
Bab IV §Kasus G.

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
error pada keluarga itu. A, F, dan G tidak ditambahkan ke keluarga. Bukti tetap
diuji sebagai diagnostik karena keluarga itu sudah ditetapkan sebelum
pengumpulan; jangan membacanya sebagai metrik utama atau keunggulan. Di naskah,
angka p dan nama uji ditempatkan di Lampiran B; Bab IV hanya memakai median.
Lihat Bab III §Analisis Data dan Lampiran B.

## 12. Mengapa C dan D memakai Mann–Whitney?

Wilcoxon hanya dipakai bila setiap blok skenario–pengulangan memiliki kedua mode
dan kedua nilai teramati. Pada C, pasangan lengkap tidak terbentuk; pada D
deteksi dan bukti juga tidak. Aturan fallback ditetapkan sebelum analisis,
bukan dipilih setelah melihat hasil. Lihat Lampiran B Tabel B.2.

## 13. Mengapa ada 15 pengamatan pemulihan yang berhenti sebelum peristiwa?

Sepuluh terjadi pada blok waktu dan lima pada blok kecocokan; seluruhnya berasal
dari mode GitOps pada skenario G. Pengamatan itu tidak mencapai titik akhir
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

## 16. Apakah atribusi pelaku perubahan diukur?

Tidak. Atribusi memerlukan audit API server untuk menghubungkan perubahan dengan
pelakunya. Audit itu tidak tersedia pada apparatus ini, sehingga atribusi
dilaporkan sebagai keterbatasan dan pekerjaan lanjutan, bukan hasil. Lihat Bab V
§Keterbatasan.

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
selang pengamatan: selisih 4,2–4,3 detik pada selang 5 detik dan 0,25–0,32 detik
pada selang 1 detik. Pemulihan tidak seragam (B/C lebih kecil, D paling besar,
E moderat; B tidak jelas dan C melemah pada sensitivitas); pada tindak lanjut,
B dan E hampir sama, C lebih cepat pada mode imperatif, dan D lebih cepat pada
GitOps. G adalah pengecualian deskriptif yang menunjukkan batas cakupan field.

## 20. Apakah refactor kode setelah koleksi membatalkan hasil?

Tidak. Apparatus koleksi ditetapkan pada `3572f3c`; kode `HEAD` bukan revisi
koleksi. Refactor pasca-koleksi diuji dengan suite tes inti (505 tes di `HEAD`;
502 tes saat refactor) + 9 tes sensitivity, keluaran analisis yang ditetapkan
identik, dan dry-run 210 sel. Untuk mengaudit angka, gunakan keluaran yang
ditetapkan dan data mentah, bukan menjalankan ulang koleksi. Lihat
`experiments/REVISIONS.md`.

## 21. Apa hasil uji tindak lanjut dengan selang 1 detik?

Batch `matched1s-20261127b` merencanakan 80 sel (B–E, dua mode, 10 pengulangan)
dengan pemeriksa dan pencatat 1 detik serta urutan berselang-seling. Dari 80 sel
terminal, 79 dianalisis; satu sel imperatif C gagal sebelum injeksi karena API
Kubernetes time-out, sehingga tidak menghasilkan baris analisis dan tidak
diimputasi. Selisih deteksi menyusut dari 4,2–4,3 detik pada selang 5 detik
menjadi 0,25–0,32 detik; ini mendukung penjelasan bahwa deteksi sebagian besar
mengikuti selang pengamatan. Pemulihan tetap bergantung skenario: B dan E hampir
sama, C lebih cepat pada mode imperatif sekitar 1,1 detik, dan D lebih cepat pada
GitOps sekitar 1,0 detik. Deteksi D GitOps hanya memiliki dua nilai teramati,
sehingga tidak dilaporkan. Batch ini memakai HPA dengan metrik CPU saja
(perubahan apparatus), satu stack, dan tidak digabungkan dengan batch 210 sel.
Uji lengkap dan ukuran efek ada di `experiments/analysis-matched1s-20261127b/live_tests.tex`
dan `live_effects.tex`; slide utama hanya memuat median. Lihat
`experiments/analysis-matched1s-20261127b/live_analysis.json` dan Bab V.

## 22. Apa pekerjaan lanjutan setelah tindak lanjut?

Subset selang 1 detik tidak lagi menjadi pekerjaan lanjutan karena batch 80 sel
sudah dijalankan. Prioritasnya: replikasi pada sekurang-kurangnya tiga stack
terisolasi; perbandingan alat GitOps kedua, misalnya Flux; pengukuran biaya dan
jam orang; studi kualitatif atau campuran; workload stateful dan stateless; serta
jendela pengamatan lebih panjang dengan penyimpanan independen. Lihat Bab V
§Pekerjaan Lanjutan.

## Bukti, kode, dan reproduksi

### Di mana bukti angkanya?

- Sesi pengumpulan `formal-20261029`: 210 sel terminal, 211 baris mentah, 207
  baris analisis, dan 4 baris dikecualikan (2 kegagalan instrumentasi, 1
  kegagalan baseline yang diulang, 1 penghentian sesi).
- Batch tindak lanjut `matched1s-20261127b`: 80 sel direncanakan, 80 terminal,
  79 dianalisis, 1 kegagalan instrumentasi (imperatif C-r02, API Kubernetes
  time-out sebelum injeksi); keluaran di
  `experiments/analysis-matched1s-20261127b/`.
- Peta klaim: `docs/reproducibility/claim-traceability.md`.
- Keluaran beku: `experiments/analysis-formal-20261029/` (tujuh berkas, termasuk
  `live_analysis.json`); data mentah dan keluaran itu tersimpan lokal dan
  diabaikan Git.

### Identitas yang ditetapkan

| Peran | Tag | Commit |
|---|---|---|
| Apparatus koleksi | `thesis-collection-20261029` | `3572f3c` |
| Analisis primer | `thesis-analysis-20261030` | `a1d43ea` |
| Analisis sensitivitas | `thesis-sensitivity-20261030` | `6cfc99e` |

`HEAD` adalah kode pasca-koleksi. Angka primer berasal dari keluaran beku, bukan
dari menjalankan ulang apparatus.

Batch tindak lanjut `matched1s-20261127b` memakai revisi sumber `2aff56d8` dan
render SHA-256 `ffff8d73b5a7ba09324582928a1a5e6597c30f1430d185bc38dc852aac541efa`.
Batch pertama `matched1s-20261127` tidak dianalisis karena revisi `81ddd25` tidak
cocok dengan render tersebut. Data mentah dan keluaran analisis batch tindak
lanjut tersimpan lokal dan diabaikan Git.

### Perintah reproduksi analisis

Dari akar repository:

```bash
D=experiments/formal-20261029
python3 experiments/analysis/analyze_live.py \
  --in $D/formal-20261029.analysis.jsonl \
  --rows $D/formal-20261029.rows.jsonl \
  --out /tmp/formal-20261029-rerun \
  --bootstrap 2000 --seed 20261029 --alpha 0.05
```

Nilai `--seed 20261029` harus dipakai; nilai bawaan kode adalah `20261027`,
sehingga tanpa flag itu interval bootstrap dan keluaran tidak identik dengan
paket beku. Setelah perintah itu:

```bash
diff -r experiments/analysis-formal-20261029 /tmp/formal-20261029-rerun
```

Satu-satunya perbedaan yang diharapkan adalah `SHA256SUMS` yang tidak ditulis
oleh analyzer. Tujuh keluaran lain harus identik. Lihat `experiments/DATA.md`
§Reproduksi Analisis.

Untuk batch tindak lanjut:

```bash
B=experiments/live/runs/matched1s-20261127b
python3 experiments/analysis/analyze_live.py \
  --in $B/matched1s-20261127b.analysis.jsonl \
  --rows $B/matched1s-20261127b.rows.jsonl \
  --out /tmp/matched1s-20261127b-rerun \
  --bootstrap 2000 --seed 20261127 --alpha 0.05
```

Bandingkan hasilnya dengan paket beku `experiments/analysis-matched1s-20261127b/`.

### Verifikasi data mentah

```bash
cd experiments/formal-20261029
shasum -a 256 -c SHA256SUMS
```

Hasil yang diharapkan: 3.024 baris `OK`, 0 gagal. Checkout tanpa data mentah
dapat memverifikasi kode dan tes, tetapi tidak dapat menghitung ulang angka
teramati.

### Analisis sensitivitas

```bash
python3 experiments/sensitivity/c_r02_sensitivity.py \
  --out /tmp/c-r02-sensitivity.json
```

Skrip ini tidak menulis ke direktori beku. Nilai sensitivitas tidak memiliki
berkas keluaran yang dikomit, sehingga statusnya dicatat sebagai gap yang dapat
direproduksi di `docs/reproducibility/claim-traceability.md`.

### Tes instrumen

```bash
python3 -m unittest discover -s experiments/tests -q                    # 505 tes
python3 -m unittest discover -s experiments/sensitivity -p 'test_*.py' -q  # 9 tes
```

`experiments/DATA.md` mencatat 492 tes dari verifikasi 2026-11-19; suite
bertambah setelah refactor. Angka 505 adalah hasil perintah di atas pada `HEAD`.

## 5-minute code walkthrough

Use this order when an examiner asks to see the apparatus. Timings are targets,
not claims; stop at the collection boundary.

| Time | Show | Say |
|---|---|---|
| 0:00 | `git rev-parse 'thesis-collection-20261029^{commit}'` and `'thesis-analysis-20261030^{commit}'` | Collection and analysis are separate; `HEAD` is post-collection. |
| 0:40 | `experiments/live/harness.py` (`build_contract`, `score`, baseline gate) | The contract is fixed; score 100 is the recovery predicate. |
| 1:40 | `experiments/live/harness.py` timing endpoints and `experiments/live/sampling.py` | `t_d`, `t_e`, `t_r` come from completed observations; no imputation; 5 s checker versus 1 s recorder. |
| 2:30 | `experiments/analysis/analyze_live.py` (`analyze`, `_r1_entries`, `_comparison`, `holm_adjust`) | The analyzer selects B–E, applies the fixed fallback rule, and keeps the configuration check descriptive. |
| 3:30 | `experiments/analysis/rq2_report.py` and `docs/defense/source-map.md` | The thesis view selects the timing fields, derives `t_r - t_d`, and maps the historical `env=manual` alias to the imperative mode while preserving `legacy_env=manual`. |
| 4:30 | `experiments/formal-20261029/PROVENANCE.json` and `experiments/DATA.md` | Raw rows and analysis outputs are local; the checkout documents and tests the code, not a recomputation of observed numbers. |

Never edit the analyzer or the collection modules during a walkthrough. If a
live rerun is requested, stop: a new collection session needs new approval, a
new identity, and a new apparatus identity.
