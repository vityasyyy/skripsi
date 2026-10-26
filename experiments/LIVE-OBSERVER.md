# Protokol observer dan kolektor otomatis

**Status: rencana, bukan prosedur yang telah diuji.** Dokumen ini merinci
observer/kolektor pasif untuk kedua lengan pada Bab III. Tidak ada eksekusi
klaster, injeksi, reset, pengambilan data, atau klaim hasil dalam dokumen ini.
Eksperimen formal belum disetujui; seluruh gerbang pada Bab III tetap berlaku.

## Ruang lingkup

- Lingkungan A adalah prosedur imperatif terotomasi tetap: pemeriksa berkala
  membandingkan keadaan aktual dengan inventaris dan nilai yang diinginkan,
  menyimpan bukti perbedaan, lalu menjalankan koreksi `kubectl` yang telah
  ditentukan.
- Lingkungan B adalah GitOps dengan ArgoCD dan rekonsiliasi otomatis.
- Observer/kolektor adalah proses **read-only otomatis** pada host pencatat. Ia
  mengambil sampel keadaan, menulis bukti, dan menghitung waktu; ia bukan
  manusia, tidak menunggu, tidak mengetik, dan tidak mengubah klaster.
- Kedua lengan dijalankan berurutan pada satu stack InvenioRDM. Hanya satu
  lengan aktif pada satu waktu. Waktu reaksi manusia bukan variabel penelitian.

## Arsitektur pengukuran

| Komponen | Fungsi | Batas |
|---|---|---|
| Kolektor | Sampling node, pod, Deployment/Service/HPA, status ArgoCD, metrics-server, alert, dan event pengendali | Read-only; tidak mengoreksi; tidak menerima label skenario |
| Injektor/runner | Mengirim satu perintah injeksi tetap, mencatat `t0`/`t_a`, memverifikasi perubahan bidang | Tidak memberi label skenario kepada mekanisme koreksi |
| Pemeriksa imperatif (A) | Membandingkan keadaan aktual dengan acuan, menyimpan bukti, menjalankan runbook koreksi | Hanya aktif pada lengan A; bukan evaluator R1 |
| ArgoCD (B) | Menjalankan rekonsiliasi terhadap deklarasi Git | Bukan pengendali HPA atau pengendali lain |
| Evaluator bersama | Menghitung R1 dari pembacaan aktual dan inventaris yang sama | Tidak menggantikan mekanisme koreksi |

Kolektor berjalan sebelum injeksi dan menulis satu bundel bukti per run dengan
`run_id`. Semua waktu berasal dari satu jam monotonik pada host pencatat; UTC
disimpan untuk audit. Tidak ada cap waktu yang direkonstruksi setelah run.

## Prasyarat dan reset ke seed bersih

Sebelum setiap run, seluruh butir berikut harus benar. Kegagalan satu butir
menggagalkan run; jangan memulai injeksi.

1. Hanya satu stack InvenioRDM aktif, di namespace eksperimen yang terpisah dari
   produksi `invenio`. Tidak ada namespace lengan kembar, objek sisa lengan
   sebelumnya, atau objek karantina.
2. Salinan seed di namespace eksperimen terverifikasi: draf privat
   `4ben9-bgh38` dengan `seed.bin` berukuran 65.536 byte, MD5
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
6. Jam host pencatat tersinkronisasi dan kolektor aktif sebelum injeksi.
7. Audit API tersedia atau ketiadaannya dicatat sebagai `tidak dapat dinilai`.
   SMTP dan HA OpenSearch tetap di luar cakupan dan tidak boleh menjadi
   prasyarat yang diam-diam ditambahkan.

Reset yang gagal harus dilaporkan dan run berikutnya dilarang sampai reset
lengkap terverifikasi. Tidak ada pengosongan queue, modifikasi data, restore,
atau migrasi yang diizinkan oleh dokumen ini.

## Urutan satu run

1. **Pra-run.** Pilih lengan dan urutan yang sudah diacak; buat `run_id`; catat
   revisi Git, digest render, image digest, dan inventaris. Simpan baseline.
   Aktifkan kolektor dan pastikan pemeriksa imperatif atau ArgoCD sudah aktif.
2. **Injeksi.** Injektor menjalankan perintah injeksi tetap dan mencatat `t0`
   (kirim) serta `t_a` (respons API). Verifikasi bahwa bidang sasaran benar-benar
   berubah. Jangan menambah jeda buatan. Jika injeksi gagal atau tidak
   terverifikasi, tandai `invalid_injection` dan jangan menghitung waktu deteksi
   nol.
3. **Pengamatan.** Kolektor mengambil sampel pada interval nominal satu detik.
   `t_d` adalah sinyal deteksi pertama dari pemeriksa imperatif (A) atau ArgoCD
   (B); `t_e` adalah bukti tersimpan pertama yang mengidentifikasi objek dan
   bidang; `t_r` adalah pembacaan pertama seluruh inventaris dan bidang cocok,
   dikonfirmasi pada pembacaan berikutnya. Kolektor tidak memberi petunjuk dan
   tidak mengubah mekanisme koreksi.
4. **Pasca-run.** Ekspor bundel bukti, hitung SHA-256, catat status akhir, dan
   tutup `run_id`. Jangan menyunting cap waktu setelah run.
5. **Reset.** Ulangi seluruh pemeriksaan reset di atas sebelum run berikutnya
   atau perpindahan lengan.

## Field waktu

Semua waktu UTC dalam ISO 8601 dan waktu monotonik dalam detik dengan pecahan.
Durasi dihitung dari jam monotonik, bukan selisih UTC. Tidak ada interpolasi;
cap waktu adalah pengamatan pertama, bukan rekonstruksi setelah fakta.

| Field | Definisi | Produsen | Validasi |
|---|---|---|---|
| `run_id` | Identitas unik run | Kolektor | Sama pada semua berkas bukti |
| `arm` | `imperative` atau `gitops` | Runner | Hanya satu lengan aktif |
| `scenario`, `rep` | Skenario A--G dan indeks pengulangan | Runner | Permutasi skenario tercatat |
| `t0_utc`, `t0_mono` | Pengiriman permintaan injeksi | Injektor | Perintah injeksi tercatat |
| `t_a_utc`, `t_a_mono` | Penerimaan respons API | Injektor | Respons API dan verifikasi bidang |
| `t_d_utc`, `t_d_mono` | Sinyal deteksi pengendali pertama | Kolektor | `detection_source` dicatat |
| `t_e_utc`, `t_e_mono` | Bukti deviasi tersimpan | Kolektor | `evidence_ref` menunjuk berkas |
| `t_r_utc`, `t_r_mono` | Pemulihan terkonfirmasi | Kolektor | Dua pembacaan cocok |
| `controller` | `hpa`, `argocd`, `imperative`, `deployment-controller`, `sealed-secrets`, `other`, `unattributed` | Kolektor | Aturan atribusi di bawah |
| `status` | `observed`, `right_censored`, `invalid_injection`, `instrumentation_failure`, `recovery_failure`, `reset_failure` | Kolektor | Tidak diisi nol |
| `notes` | Anomali, jeda polling, offset jam | Kolektor | Faktual, tanpa spekulasi |

Durasi yang dilaporkan: `t_d - t0`, `t_e - t0`, dan `t_r - t0`. Tidak ada field
akar masalah manusia; `t_e` hanya menunjukkan ketersediaan bukti deviasi, bukan
penyebab kausal.

## Bukti yang disimpan

| Bukti | Isi minimum | Sumber | Penanganan |
|---|---|---|---|
| Revisi dan render | Revisi Git 40 heksadesimal, SHA-256 hasil render, image digest | Repositori dan ekspor render | Bekukan sebelum run; bukan manifest editable baru |
| Status ArgoCD | `Application` status, sync operation, diff, event, dan kondisi | `kubectl -n argocd get application`, `argocd app get/diff` | Sanitasi; jangan sertakan token |
| Log perintah | Perintah injeksi/koreksi, waktu mulai/akhir, exit code, keluaran relevan | Runner dan runbook otomatis | Jangan sertakan Secret |
| Snapshot manifest | Objek sebelum dan sesudah, bidang terpilih | `kubectl get -o yaml` | Hapus `managedFields`, `resourceVersion`, status server, dan nilai Secret |
| Alert | Nama alert, `startsAt`, label, fingerprint | Alertmanager/Grafana | Jangan hanya menyalin teks pesan |
| Audit API | Aktor, objek, bidang, waktu | Audit log API bila tersedia | Jika tidak tersedia, catat `tidak dapat dinilai` |
| HPA | Target, replika aktual, event, kondisi | `kubectl -n invenio get hpa -o yaml`, event | Terpisah dari R1 statis |
| Seed dan reset | ID draf, ukuran dan SHA-256 berkas, jumlah record/berkas, status antrean/index | Invenio dan `kubectl` | Seed tidak boleh diubah |
| Log kolektor | Interval aktual, jeda polling, kegagalan baca, versi kolektor | Kolektor | Di-hash setelah run |

Setiap berkas bukti memakai `run_id` yang sama. Berkas tanpa `run_id` atau
berasal dari run lain ditolak, bukan dianggap observasi run ini.

## Aturan atribusi pengendali

Atribusi dilakukan sebelum analisis, bukan setelah melihat hasil.

- **HPA.** Perubahan jumlah replika, status HPA, dan event scale adalah sinyal
  HPA. HPA adalah pemilik normal replika pada kedua lengan. Pemulihan replika
  oleh HPA tidak dihitung sebagai deteksi atau pemulihan ArgoCD, dan tidak
  dihitung sebagai koreksi imperatif. `/spec/replicas` dikecualikan dari R1
  statis untuk Deployment yang dimiliki HPA; status HPA dilaporkan terpisah.
- **ArgoCD.** Deteksi dan pemulihan ArgoCD hanya dihitung untuk bidang terkelola
  pada skenario B--E dan G yang benar-benar dipulihkan oleh rekonsiliasi.
  `OutOfSync` karena `/spec/replicas`, objek F di luar cakupan, atau perubahan
  yang dilakukan pengendali lain bukan bukti self-heal ArgoCD.
- **Pemeriksa imperatif.** Deteksi dan koreksi A hanya dihitung untuk bidang
  terkelola pada skenario B--E dan G yang benar-benar dijalankan oleh runbook.
  Sinyal HPA bukan deteksi imperatif.
- **Deployment controller.** Pembuatan ulang Pod atau rollout setelah Deployment
  berubah adalah konsekuensi, bukan pemulihan konfigurasi. Pemulihan dinilai dari
  kesetaraan inventaris dan bidang, bukan dari status rollout.
- **Pengendali lain.** SealedSecret, ImageUpdater, CNPG, Redis, OpenSearch, dan
  Velero tidak dihitung sebagai ArgoCD atau pemeriksa imperatif. Perubahan laten
  ImageUpdater dan SealedSecret harus dibekukan atau diisolasi sesuai kontrak
  yang disetujui.
- **Tidak pasti.** Jika pengendali tidak dapat dipastikan, isi `unattributed`
  dan keluarkan dari klaim efikasi ArgoCD maupun imperatif. Jangan menebak.

Skenario A dilaporkan sebagai kontrol HPA; skenario F sebagai batas visibilitas
objek tak terkelola. Keduanya tidak digabungkan ke estimasi efikasi B--E/G.

## Kegagalan, penyensoran, dan validitas

- Injeksi yang gagal atau tidak terverifikasi adalah `invalid_injection`, bukan
  deteksi nol.
- Kegagalan pembacaan API atau kolektor adalah `instrumentation_failure`, bukan
  deteksi yang terlewat.
- Tidak ada sinyal sampai batas pengamatan adalah `right_censored` dengan batas
  waktu; waktu hilang tetap kosong.
- Pemulihan yang gagal atau reset yang gagal dicatat sebagai kegagalan, bukan
  dibuang agar hanya run sukses yang tersisa.
- Tidak ada waktu reaksi manusia yang diukur; kedua lengan berjalan otomatis.
  Resolusi kolektor serta interval pemeriksa imperatif dan rekonsiliasi ArgoCD
  membatasi ketepatan waktu.
- Lengan dijalankan berurutan, sehingga kondisi klaster antarblok dapat berbeda.
  Urutan lengan diacak, kondisi dicatat, dan reset diverifikasi; perbedaan waktu
  tidak dianggap tereliminasi.
- Satu kolektor dan satu implementasi otomasi imperatif membatasi generalisasi.
  Replikasi dengan konfigurasi berbeda dianjurkan, bukan diklaim oleh dokumen
  ini.
- Diff atau `t_e` hanya menunjukkan deviasi, bukan penyebab kausal. R3 tetap
  rubrik deskriptif, bukan uji statistik.

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

## Instrumen live

Protokol ini diimplementasikan sebagai harness di
[`live/README.md`](live/README.md). Harness berjalan dry-run secara default,
memakai `kubectl` tanpa shell, dan menargetkan stack InvenioRDM nyata. Dokumen
tersebut memuat prosedur lengan berurutan, tabel skenario, skema bukti/CSV, serta
gerbang formal yang masih terbuka; isi protokol dan batas interpretasi tetap
berlaku.

## Rujukan

- `content/proposal/chapters/bab3-metodologi.tex` — definisi R1--R3, HPA, dan
  gerbang baseline.
- `experiments/README.md` — kontrak bukti dan instrumen offline.
- `experiments/live/README.md` — harness live dry-run default, prosedur lengan,
  skenario, bukti/CSV, dan gerbang yang tersisa.
- `experiments/deployment-source.json` — sumber deployment yang diperiksa.
- `invenio-rdm-gitops/docs/current-state.md` — snapshot lingkungan 25 Oktober
  2026 dan gerbang kesiapan.
