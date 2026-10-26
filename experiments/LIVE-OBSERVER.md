# Protokol lengan manual dan observer live

**Status: rencana, bukan prosedur yang telah diuji.** Dokumen ini merinci lengan
manual (Lingkungan A) pada Bab III. Tidak ada eksekusi klaster, injeksi, reset,
pengambilan data, atau klaim hasil dalam dokumen ini. Eksperimen formal belum
disetujui; seluruh gerbang pada Bab III tetap berlaku.

## Ruang lingkup dan peran

Lengan A adalah prosedur manual: operator manusia menjalankan diagnosis dan
koreksi `kubectl` sesuai runbook. Pemeriksa kesetaraan bersifat read-only dan
tidak menggantikan operator. Lengan B adalah GitOps/ArgoCD. Kedua lengan
dijalankan berurutan pada satu stack InvenioRDM; hanya satu lengan aktif pada
satu waktu.

| Peran | Tanggung jawab | Batas |
|---|---|---|
| Operator | Menjalankan diagnosis dan koreksi sesuai runbook; melaporkan deteksi dan diagnosis kepada observer | Tidak menerima label skenario, tidak melihat keluaran pemeriksa kesetaraan selama run, tidak mengubah runbook |
| Observer | Mencatat cap waktu, sumber deteksi, bukti, dan transkrip; menjaga urutan berkas bukti | Tidak memberi petunjuk, tidak mengoreksi, tidak menghentikan run kecuali alasan keselamatan |
| Injektor/lead | Mengacak urutan, mengirim injeksi, memverifikasi penerimaan, mengendalikan reset, menyimpan berkas bukti | Tidak menjadi operator pada run yang sama bila dapat dihindari |

Pemisahan operator dan observer diutamakan. Jika satu orang harus merangkap,
catat perangkapan tersebut sebagai keterbatasan dan jangan mengeklaim
independensi pengamatan.

## Prasyarat dan reset ke seed bersih

Sebelum setiap run, seluruh butir berikut harus benar. Kegagalan satu butir
menggagalkan run; jangan memulai injeksi.

1. Hanya satu stack InvenioRDM aktif, di namespace eksperimen yang terpisah dari
   produksi `invenio`. Tidak ada namespace aplikasi kembar, objek sisa lengan
   sebelumnya, atau objek karantina.
2. Seed bersih terverifikasi: salinan draf privat `4ben9-bgh38` di namespace
   eksperimen dengan `seed.bin` berukuran 65.536 byte, MD5
   `8f1445bafe2c2095044af7789462f475`, dan SHA-256
   `7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2`
   masih ada; tidak ada record, draft, atau berkas lain di luar seed. Jalur
   unggah/unduh seed sudah terverifikasi, tetapi pemulihan record/berkas setelah
   seed belum diuji.
3. Konfigurasi, Secret, dan antrean kembali ke acuan; HPA berada pada keadaan
   normal; semua pod layanan Running dan Ready.
4. Dua pembacaan lengkap yang berurutan cocok. Rollout sehat saja bukan bukti
   reset.
5. CPU dan memori setiap node di bawah 70% (working set metrics-server dibagi
   allocatable), dengan jendela pengamatan yang dicatat.
6. Jam host pencatat tersinkronisasi; observer dan kolektor memakai sumber jam
   yang sama. Offset antarmuka observer dicatat bila terpisah.
7. Audit API tersedia atau ketiadaannya dicatat sebagai `tidak dapat dinilai`.
   SMTP dan HA OpenSearch tetap di luar cakupan dan tidak boleh menjadi
   prasyarat yang diam-diam ditambahkan.

Reset yang gagal harus dilaporkan dan run berikutnya dilarang sampai reset
lengkap terverifikasi. Tidak ada pengosongan queue, modifikasi data, restore,
atau migrasi yang diizinkan oleh dokumen ini.

## Urutan satu run

1. **Pra-run.** Pilih lengan dan urutan yang sudah diacak; buat `run_id`; catat
   revisi Git, digest render, image digest, dan inventaris. Simpan baseline.
   Aktifkan kolektor dan siapkan lembar observer. Operator diberi tahu bahwa run
   dimulai, tetapi tidak diberi label skenario.
2. **Injeksi.** Injektor menjalankan perintah injeksi tetap dan mencatat
   `t0` (kirim) serta `t_a` (respons API). Verifikasi bahwa bidang sasaran
   benar-benar berubah. Jangan menambah jeda buatan. Jika injeksi gagal atau
   tidak terverifikasi, tandai `invalid_injection` dan jangan menghitung waktu
   deteksi nol.
3. **Deteksi.** Operator bekerja dari observabilitas normal dan pemeriksaan
   `kubectl`. Observer mencatat `t_d` saat operator pertama melaporkan sinyal,
   beserta sumbernya (alert, status, log, atau pemeriksaan manual). Observer
   tidak memberi petunjuk.
4. **Diagnosis.** Operator mengikuti runbook. Observer mencatat `t_e` saat bukti
   yang mengidentifikasi objek dan bidang tersimpan, lalu `t_rci` saat operator
   menyatakan penyebab atau bidang penyimpangan. Catat kategori dan referensi
   bukti. `t_rci` adalah diagnosis operasional, bukan bukti kausal penuh.
5. **Pemulihan.** Operator menjalankan perintah koreksi. Observer mencatat awal
   dan akhir setiap perintah, exit code, dan keluaran yang relevan. Pemeriksa
   read-only memverifikasi dua pembacaan lengkap; `t_r` adalah pembacaan pertama
   yang cocok. Pemulihan replika oleh HPA bukan koreksi operator.
6. **Pasca-run.** Ekspor bukti, hitung SHA-256 berkas bukti, catat status akhir,
   dan tutup lembar observer. Jangan menyunting cap waktu setelah run.
7. **Reset.** Ulangi seluruh pemeriksaan reset di atas sebelum run berikutnya
   atau perpindahan lengan.

## Field waktu

Semua waktu UTC dalam ISO 8601 dan waktu monotonik dalam detik dengan pecahan.
Durasi dihitung dari jam monotonik, bukan selisih UTC. Tidak ada interpolasi;
cap waktu adalah pengamatan pertama, bukan rekonstruksi setelah fakta.

| Field | Definisi | Pencatat | Validasi |
|---|---|---|---|
| `run_id` | Identitas unik run | Lead | Sama pada semua berkas bukti |
| `arm` | `manual` atau `gitops` | Lead | Hanya satu lengan aktif |
| `scenario`, `rep` | Skenario A--G dan indeks pengulangan | Lead | Permutasi skenario tercatat |
| `t0_utc`, `t0_mono` | Pengiriman permintaan injeksi | Injektor | Perintah injeksi tercatat |
| `t_a_utc`, `t_a_mono` | Penerimaan respons API | Injektor | Respons API dan verifikasi bidang |
| `t_d_utc`, `t_d_mono` | Deteksi pertama | Observer | `td_source` dicatat |
| `t_e_utc`, `t_e_mono` | Bukti deviasi tersimpan | Observer | `evidence_ref` menunjuk berkas |
| `t_rci_utc`, `t_rci_mono` | Identifikasi akar masalah operasional (A) | Observer | `rci_category`, `rci_evidence` |
| `t_r_utc`, `t_r_mono` | Pemulihan terkonfirmasi | Observer | Dua pembacaan cocok |
| `controller` | `hpa`, `argocd`, `imperative`, `deployment-controller`, `sealed-secrets`, `other`, `unattributed` | Observer | Aturan atribusi di bawah |
| `status` | `observed`, `right_censored`, `invalid_injection`, `instrumentation_failure`, `recovery_failure`, `reset_failure` | Lead | Tidak diisi nol |
| `notes` | Anomali, offset jam, perangkapan peran | Observer | Faktual, tanpa spekulasi |

Durasi yang dilaporkan: `t_d - t0`, `t_e - t0`, `t_r - t0`, dan untuk lengan
manual `t_rci - t_d` secara deskriptif. Pada lengan GitOps, `t_rci` tidak diisi;
waktu yang tersedia adalah `t_e`. Jangan membandingkan `t_rci` manual dengan
`t_e` GitOps sebagai metrik yang setara.

## Bukti yang disimpan

| Bukti | Isi minimum | Sumber | Penanganan |
|---|---|---|---|
| Revisi dan render | Revisi Git 40 heksadesimal, SHA-256 hasil render, image digest | Repositori dan ekspor render | Bekukan sebelum run; bukan manifest editable baru |
| Status ArgoCD | `Application` status, sync operation, diff, event, dan kondisi | `kubectl -n argocd get application`, `argocd app get/diff` | Sanitasi; jangan sertakan token |
| Transkrip perintah | Perintah, waktu mulai/akhir, exit code, keluaran relevan | `script`/typescript, shell history, lembar observer | Jangan sertakan Secret |
| Snapshot manifest | Objek sebelum dan sesudah, bidang terpilih | `kubectl get -o yaml` | Hapus `managedFields`, `resourceVersion`, status server, dan nilai Secret |
| Alert | Nama alert, `startsAt`, label, fingerprint | Alertmanager/Grafana | Jangan hanya menyalin teks pesan |
| Audit API | Aktor, objek, bidang, waktu | Audit log API bila tersedia | Jika tidak tersedia, catat `tidak dapat dinilai` |
| HPA | Target, replika aktual, event, kondisi | `kubectl -n invenio get hpa -o yaml`, event | Terpisah dari R1 statis |
| Seed dan reset | ID draf, ukuran dan SHA-256 berkas, jumlah record/berkas, status antrean/index | Invenio dan `kubectl` | Seed tidak boleh diubah |
| Catatan observer | `td_source`, kategori diagnosis, anomali, offset jam | Lembar observer | Ditandatangani/di-hash setelah run |

Setiap berkas bukti memakai `run_id` yang sama. Berkas tanpa `run_id` atau
berasal dari run lain ditolak, bukan dianggap observasi run ini.

## Aturan atribusi pengendali

Atribusi dilakukan sebelum analisis, bukan setelah melihat hasil.

- **HPA.** Perubahan jumlah replika, status HPA, dan event scale adalah sinyal
  HPA. HPA adalah pemilik normal replika pada kedua lengan. Pemulihan replika
  oleh HPA tidak dihitung sebagai deteksi atau pemulihan ArgoCD, dan tidak
  dihitung sebagai koreksi operator manual. `/spec/replicas` dikecualikan dari
  R1 statis untuk Deployment yang dimiliki HPA; status HPA dilaporkan terpisah.
- **ArgoCD.** Deteksi dan pemulihan ArgoCD hanya dihitung untuk bidang terkelola
  pada skenario B--E dan G yang benar-benar dipulihkan oleh rekonsiliasi.
  `OutOfSync` karena `/spec/replicas`, objek F di luar cakupan, atau perubahan
  yang dilakukan pengendali lain bukan bukti self-heal ArgoCD.
- **Deployment controller.** Pembuatan ulang Pod atau rollout setelah Deployment
  berubah adalah konsekuensi, bukan pemulihan konfigurasi. Pemulihan dinilai dari
  kesetaraan inventaris dan bidang, bukan dari status rollout.
- **Pengendali lain.** SealedSecret, ImageUpdater, CNPG, Redis, OpenSearch, dan
  Velero tidak dihitung sebagai ArgoCD atau operator manual. Perubahan laten
  ImageUpdater dan SealedSecret harus dibekukan atau diisolasi sesuai kontrak
  yang disetujui.
- **Tidak pasti.** Jika pengendali tidak dapat dipastikan, isi `unattributed`
  dan keluarkan dari klaim efikasi ArgoCD. Jangan menebak.

Skenario A dilaporkan sebagai kontrol HPA; skenario F sebagai batas visibilitas
objek tak terkelola. Keduanya tidak digabungkan ke estimasi efikasi B--E/G.

## Kegagalan, penyensoran, dan validitas

- Injeksi yang gagal atau tidak terverifikasi adalah `invalid_injection`, bukan
  deteksi nol.
- Kegagalan pembacaan API, kolektor, atau observer adalah
  `instrumentation_failure`, bukan deteksi yang terlewat.
- Tidak ada sinyal sampai batas pengamatan adalah `right_censored` dengan batas
  waktu; waktu hilang tetap kosong.
- Pemulihan yang gagal atau reset yang gagal dicatat sebagai kegagalan, bukan
  dibuang agar hanya run sukses yang tersisa.
- Kehadiran observer dan pengetahuan bahwa run diukur dapat menimbulkan
  Hawthorne effect; operator mengikuti runbook tetap, observer tidak memberi
  petunjuk, dan practice run dilakukan. Bias ini tetap dilaporkan.
- Lengan dijalankan berurutan, sehingga kondisi klaster antarblok dapat berbeda.
  Urutan lengan diacak, kondisi dicatat, dan reset diverifikasi; perbedaan waktu
  tidak dianggap tereliminasi.
- Satu operator dan satu observer membatasi generalisasi. Replikasi dengan
  operator/observer berbeda dianjurkan, bukan diklaim oleh dokumen ini.

## Larangan

Dokumen ini tidak memberikan izin untuk:

- menjalankan injeksi, polling, pemulihan, atau reset pada klaster;
- menyentuh namespace produksi `invenio`, `argocd`, `database`, `monitoring`,
  `velero`, atau objek bersama;
- membaca, menyalin, atau menerbitkan nilai Secret;
- melakukan restore, purge queue/data, migrasi, deploy, atau perubahan
  pengendali;
- mengarang cap waktu, status, atau hasil yang tidak teramati.

Jika terjadi pelanggaran keselamatan atau kondisi tak terduga, hentikan run,
catat waktunya, dan tandai run sebagai gagal. Jangan melanjutkan ke run berikutnya
sebelum reset lengkap terverifikasi.

## Rujukan

- `content/proposal/chapters/bab3-metodologi.tex` — definisi R1--R3, HPA, dan
  gerbang baseline.
- `experiments/README.md` — kontrak bukti dan instrumen offline.
- `experiments/deployment-source.json` — sumber deployment yang diperiksa.
- `invenio-rdm-gitops/docs/current-state.md` — snapshot lingkungan 25 Oktober
  2026 dan gerbang kesiapan.
