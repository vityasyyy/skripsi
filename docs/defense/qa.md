# Defense Q&A — ringkas dan dapat dilacak

Dokumen ini adalah alat latihan sidang, bukan bagian dari naskah skripsi.
Setiap jawaban menunjuk ke Bab/tabel atau ke artefak reproduksi. Angka hasil
berasal dari `experiments/analysis-formal-20261029/live_analysis.json` dan
`experiments/formal-20261029/formal-20261029.summary.json`.

## 1. Mengapa 210 sel, 211 baris mentah, dan 207 baris analisis?

210 sel adalah rencana 7 skenario × 2 mode × 15 pengulangan. Ada 211 baris
mentah karena satu sel, `gitops-C-r08`, gagal pada baseline pra-injeksi dan
diulang satu kali. Analisis menerima 207 baris dan mengecualikan empat baris
mentah; tiga sel tidak menghasilkan baris analisis, sedangkan `C-r08` tetap
dianalisis melalui `-retry1`. Lihat Bab IV Tabel 4.1 dan `experiments/DATA.md`.

## 2. Mengapa kesehatan layanan bukan hasil komparatif?

R1 adalah pemeriksaan validitas manipulasi, bukan pertanyaan komparatif. Status
Running/Ready dipakai sebagai guardrail kesiapan sebelum injeksi dan
postcondition setelah pemulihan; status itu tidak diskor, tidak dibandingkan
antarmode, dan tidak masuk penyebut R1. Menggabungkannya ke R1 akan mencampur
kesetaraan field dengan kesehatan layanan. Lihat Bab I §Rumusan Masalah, Bab III
§Pemeriksaan Validitas Manipulasi, dan Bab IV §Kesehatan Layanan sebagai
Guardrail.

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

Urutan mode ditetapkan sebelum koleksi untuk menjaga protokol dan
keterlacakan; urutan skenario diacak dari seed. Seluruh run GitOps mendahului
seluruh run imperatif. Karena urutan mode tetap, efek periode tidak dapat
dipisahkan sepenuhnya dari efek mode. Pengulangan berbagi satu stack dan satu
periode, sehingga pengulangan bersifat pseudoreplikat dan nilai p adalah
ringkasan deskriptif, bukan estimasi kausal atau estimasi populasi. Lihat Bab III
§Ancaman Validitas dan Bab IV §Batas Klaim.

## 6. Mengapa disebut uji berpasangan jika bukan subjek yang sama?

Pasangan dibentuk dari blok skenario–nomor pengulangan, bukan dari subjek atau
run yang sama. Kedua mode berjalan berurutan pada satu stack, sehingga
Wilcoxon di sini adalah perbandingan blok, bukan repeated measures pada unit
yang sama. Nilai p tetap eksploratif. Lihat Bab III dan catatan Tabel 4.4.

## 7. Mengapa 12 hipotesis dan koreksi Holm?

Keluarga uji ditetapkan sebelum koleksi: empat skenario efikasi B–E × tiga
metrik waktu (deteksi, bukti, pemulihan) = 12. Holm mengendalikan family-wise
error pada keluarga itu. A, F, dan G tidak ditambahkan ke keluarga. Lihat
Bab III dan Tabel 4.4.

## 8. Mengapa C dan D memakai Mann–Whitney?

Wilcoxon hanya dipakai bila setiap blok skenario–replikasi memiliki kedua mode
dan kedua nilai teramati. Pada C, pasangan lengkap tidak terbentuk; pada D
deteksi dan bukti juga tidak. Aturan fallback ditetapkan sebelum analisis,
bukan dipilih setelah melihat hasil. Lihat Bab IV Tabel 4.4 dan catatan metode.

## 9. Apa arti Cliff's δ = 1,00, dan mengapa p-value tetap eksploratif?

δ = 1,00 berarti seluruh pengamatan satu mode lebih besar daripada mode lain
pada metrik itu. Nilai p dan interval tetap dilaporkan sebagai ringkasan
eksploratif karena observasi tidak independen: satu stack, urutan mode tetap,
dan pasangan bukan subjek yang sama. Lihat Bab IV §Batas Klaim.

## 10. Mengapa ada 15 kejadian sensoring pada pemulihan?

Sepuluh terjadi pada blok waktu dan lima pada blok validitas; seluruhnya berasal dari mode GitOps pada
skenario G. Observasi tersebut tidak mencapai titik akhir dalam horizon 300
detik, jadi dilaporkan tersensor kanan, bukan kegagalan instrumen dan bukan
nilai nol. Tidak ada imputasi. Lihat Tabel 4.3 dan `experiments/DATA.md`.

## 11. Apakah G membuktikan ArgoCD gagal atau masalah izin?

Tidak. G menunjukkan anotasi SealedSecret tidak kembali ke desired state dalam
300 detik pada mode GitOps. Mekanisme yang paling mungkin adalah cakupan diff
dan client-side apply, tetapi mekanisme itu tidak diukur. Status formalnya
`unattributed`; tidak ada bukti masalah izin. G adalah kasus batas deskriptif,
bukan uji self-heal ArgoCD. Lihat Bab IV §Kasus Batas G.

## 12. Mengapa F tidak masuk keluarga efikasi B–E?

F adalah drift `targetPort` pada Service yang dideklarasikan. Field itu berada
dalam jangkauan kedua mode, tetapi keluarga 12 hipotesis B–E sudah ditetapkan
sebelum koleksi. Menambahkan F setelah melihat hasil akan merusak
predeklarasi; karena itu F dilaporkan terpisah. Label mesin lama
`visibility_boundary` dipertahankan hanya untuk kompatibilitas keluaran.
Lihat Bab III dan `experiments/analysis/README.md`.

## 13. Mengapa skenario A tetap 100?

A adalah kontrol HPA. `/spec/replicas` dimiliki HPA dan dikecualikan dari field
statis R1. Karena itu A tidak dapat dibaca sebagai keberhasilan ArgoCD atau
kegagalan prosedur imperatif; A hanya kontrol respons HPA. Lihat Bab IV
Tabel 4.2.

## 14. Mengapa satu ketidakcocokan menghasilkan skor 75?

Penyebut R1 adalah empat resource terpilih: Deployment, ConfigMap, Service,
dan SealedSecret. Satu resource yang tidak cocok = 3/4 = 75; seluruhnya cocok =
100. R1 adalah predikat pemulihan dan pemeriksaan validitas manipulasi, bukan
hasil komparatif. Lihat Bab III §Pemeriksaan Validitas Manipulasi.

## 15. Mengapa setiap metrik waktu punya 137 baris, bukan 140?

Tiga sel blok waktu tidak menghasilkan baris analisis. Untuk setiap metrik, 137 baris
tersusun dari kombinasi teramati, tersensor, dan tidak teramati sebelum
berhenti: deteksi 121+10+6; bukti 134+0+3; pemulihan 127+10+0. Kategori
`unobserved_before_stop` bukan penyensoran dan tidak diimputasi. Lihat catatan
Tabel 4.3.

## 16. Mengapa ada empat baris dengan t_e < t_d? Apakah waktunya negatif?

Tidak. t_d dan t_e berasal dari dua jalur pengamatan yang berbeda; evaluasi
bukti dapat selesai sebelum sinyal deteksi terbaca. Selisih bertanda dilaporkan
apa adanya, tidak dibulatkan menjadi nol. Empat baris itu semuanya GitOps:
B-r02, B-r06, C-r04, E-r04. Lihat Bab III §Waktu Deteksi, Ketersediaan Bukti, dan Pemulihan dan Bab IV.

## 17. Apa yang tidak dibuktikan oleh kesetaraan konfigurasi?

Kesetaraan tidak membuktikan kebenaran semantik, keamanan, atau kualitas
deklarasi. Kedua mode dapat mencapai kondisi identik dan sama-sama salah bila
deklarasi sumbernya keliru. R1 juga tidak menilai kesehatan layanan secara
umum. Lihat Bab V §Batas Kesimpulan.

## 18. Mengapa R3 tidak diukur?

R3 (traceability/audit API) membutuhkan audit log API server yang tidak
tersedia pada apparatus ini. R3 dilaporkan sebagai `not_measured` dan menjadi
pekerjaan lanjutan, bukan hasil. Lihat Bab III dan Bab V.

## 19. Mengapa tidak ada salinan off-site?

Kedua mode berbagi satu domain kegagalan penyimpanan; salinan off-site belum
tersedia. Ini keterbatasan lingkungan yang dinyatakan terbuka, bukan klaim
recovery yang sudah selesai. Lihat Bab V §Keterbatasan.

## 20. Apakah refactor kode setelah koleksi membatalkan hasil?

Tidak. Apparatus koleksi dibekukan pada `3572f3c`; kode `HEAD` bukan revisi
koleksi. Refactor pasca-koleksi diuji dengan 502 tes inti + 9 tes sensitivity,
keluaran analisis beku yang identik, dan dry-run 210 sel. Untuk mengaudit
angka, gunakan keluaran beku dan data mentah, bukan menjalankan ulang batch.
Lihat `experiments/REVISIONS.md`.

## 21. Mengapa analisis sensitivitas C-r02 penting?

`gitops-C-r02` adalah run lengkap dan teramati yang dikecualikan konservatif
sebagai `batch_stop` karena proses harness keluar non-zero. Analisis sensitivitas
menyertakannya dan menunjukkan arah kesimpulan tetap, tetapi efek pemulihan C
turun dari 0,75 ke 0,64 dan batas bawah IK turun dari 0,25 ke 0,11. Karena itu
klaim pemulihan C dibaca sebagai efek positif yang tidak seragam. Lihat Bab IV
§Analisis Sensitivitas.

## 22. Apa satu kalimat yang harus diingat penguji?

Pada apparatus, protokol, dan cakupan field yang diuji, B–F kembali ke predikat
R1 dan G adalah pengecualian deskriptif; GitOps lebih cepat pada sinyal yang
teramati di bawah cadence masing-masing untuk deteksi dan bukti, tetapi selisih
pemulihan tidak seragam (B δ = 0,48 dengan IK yang mencakup nol) dan tidak
boleh digeneralisasi menjadi superioritas universal.

## 5-minute code walkthrough

Use this order when an examiner asks to see the apparatus. Timings are targets,
not claims; stop at the frozen boundary.

| Time | Show | Say |
|---|---|---|
| 0:00 | `git rev-parse 'thesis-collection-20261029^{commit}'` and `'thesis-analysis-20261030^{commit}'` | Collection and analysis are separate freezes; `HEAD` is post-collection. |
| 0:40 | `experiments/live/harness.py` (`build_contract`, `score`, baseline gate) | The contract is frozen; R1 = 100 is the recovery predicate. |
| 1:40 | `experiments/live/harness.py` timing endpoints and `experiments/live/sampling.py` | `t_d`, `t_e`, `t_r` come from completed observations; no imputation; 5 s checker versus 1 s sampler. |
| 2:30 | `experiments/analysis/analyze_live.py` (`analyze`, `_r1_entries`, `_comparison`, `holm_adjust`) | The analyzer selects B–E, applies the frozen fallback rule, and keeps R1 descriptive. |
| 3:30 | `experiments/analysis/rq2_report.py` and `docs/defense/source-map.md` | The thesis view selects six analyzer fields, derives `t_r - t_d`, and maps the historical `env=manual` alias to `arm=imperative` while preserving `legacy_env=manual`. |
| 4:30 | `experiments/formal-20261029/PROVENANCE.json` and `experiments/DATA.md` | Raw rows and frozen outputs are local; the checkout documents and tests the code, not a recomputation of observed numbers. |

Never edit the frozen analyzer or the collection modules during a walkthrough.
If a live rerun is requested, stop: a new batch needs new approval, a new
freeze, and a new apparatus identity.
