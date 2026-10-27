# Protokol observer dan kolektor otomatis

**Status: rencana, bukan prosedur yang telah diuji secara formal.** Dokumen ini
merinci observer/kolektor pasif untuk kedua mode pada Bab III. Tidak ada klaim
hasil formal dalam dokumen ini. Eksperimen formal belum disetujui; seluruh
gerbang pada Bab III tetap berlaku. Pilot terbatas pada 27 Oktober 2026 memakai
stack yang sama dan merupakan bukti pilot, bukan data formal.

## Ruang lingkup dan desain

- **Satu stack InvenioRDM produksi-like** di namespace `invenio`. Tidak ada
  stack kembar `exp-*`, tidak ada deployment kembar, dan tidak ada eksekusi
  paralel A/B.
- **Mode imperatif** adalah mode pengelolaan pada stack yang sama: `auto-sync`
  dan `self-heal` ArgoCD dijeda sementara, pemeriksa berkala membandingkan
  keadaan aktual dengan inventaris dan nilai yang diinginkan, menyimpan bukti
  perbedaan, lalu menjalankan koreksi `kubectl` yang telah ditentukan. Setelah
  blok selesai, ArgoCD dipulihkan dan diverifikasi.
- **Mode GitOps** menggunakan stack dan acuan yang sama dengan ArgoCD aktif.
- Observer/kolektor adalah proses **read-only otomatis** pada host pencatat. Ia
  mengambil sampel keadaan, menulis bukti, dan menghitung waktu; ia bukan
  manusia, tidak menunggu, tidak mengetik, dan tidak mengubah klaster.
- Kedua mode dijalankan berurutan pada satu stack. Hanya satu mode aktif pada
  satu waktu. Waktu reaksi manusia bukan variabel penelitian.
- Karena satu stack dipakai bergantian, perlakuan **tidak terisolasi** dari
  beban latar, dependensi bersama, dan keadaan klaster yang berubah. Ini
  keterbatasan eksplisit studi kasus tunggal, bukan variabel yang dikendalikan.

## Rencana sampel formal

| Butir | Nilai |
|---|---|
| Skenario | 7 (A--G) |
| Mode | 2 (imperatif, GitOps) |
| Pengulangan per sel | 15 (10 protokol R2 + 5 protokol R1) |
| Total run | 7 × 2 × 15 = **210** |
| Sampling | interval nominal **1 detik** |
| Freeze sebelum run | revisi sumber, SHA-256 render, image digest, versi runtime |

Pembacaan R1 tetap disimpan pada setiap run sebagai bukti status; 5 pengulangan
R1 diarahkan pada protokol konsistensi. Target 210 bukan hasil analisis daya dan
tidak menjamin daya uji per skenario. R3 tidak diukur, sehingga tidak ada
pengulangan tambahan untuk R3.

## Arsitektur pengukuran

| Komponen | Fungsi | Batas |
|---|---|---|
| Kolektor | Sampling node, pod, Deployment/Service/HPA, status ArgoCD, metrics-server, alert, dan event pengendali | Read-only; tidak mengoreksi; tidak menerima label skenario |
| Injektor/runner | Mengirim satu perintah injeksi tetap, mencatat `t0`/`t_a`, memverifikasi perubahan bidang | Tidak memberi label skenario kepada mekanisme koreksi |
| Pemeriksa imperatif | Membandingkan keadaan aktual dengan acuan, menyimpan bukti, menjalankan runbook koreksi | Hanya aktif pada mode imperatif; bukan evaluator R1 |
| ArgoCD | Menjalankan rekonsiliasi terhadap deklarasi Git | Dijeda pada mode imperatif; bukan pengendali HPA atau pengendali lain |
| Evaluator bersama | Menghitung R1 dari pembacaan aktual dan inventaris yang sama | Tidak menggantikan mekanisme koreksi |

Kolektor berjalan sebelum injeksi dan menulis satu bundel bukti per run dengan
`run_id`. Semua waktu berasal dari satu jam monotonik pada host pencatat; UTC
disimpan untuk audit. Tidak ada cap waktu yang direkonstruksi setelah run.

## Prasyarat dan reset

Sebelum setiap run, seluruh butir berikut harus benar. Kegagalan satu butir
menggagalkan run; jangan memulai injeksi.

1. Hanya satu stack InvenioRDM aktif di namespace `invenio`. Tidak ada namespace
   aplikasi kembar, objek sisa blok sebelumnya, atau objek karantina.
2. Salinan seed di namespace `invenio` terverifikasi: draf privat
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
7. Revisi sumber, SHA-256 render, image digest, dan versi runtime telah
   dibekukan. Nilai yang direkonstruksi setelah hasil terlihat ditolak.
8. Mode sesuai jadwal: untuk mode imperatif, `auto-sync`/`self-heal` pada `apps`
   dan `invenio-bootstrap` terverifikasi jeda; untuk mode GitOps, keduanya
   terverifikasi aktif.
9. Audit API tidak tersedia. Ketiadaannya dicatat sebagai batas R3 dan **bukan**
   gerbang deployment. SMTP dan HA OpenSearch tetap di luar cakupan dan tidak
   boleh menjadi prasyarat yang diam-diam ditambahkan.

Reset yang gagal harus dilaporkan dan run berikutnya dilarang sampai reset
lengkap terverifikasi. Tidak ada pengosongan queue, modifikasi data, restore,
atau migrasi yang diizinkan oleh dokumen ini.

## Urutan satu run

1. **Pra-run.** Pilih mode dan urutan yang sudah diacak; buat `run_id`; catat
   revisi Git, digest render, image digest, versi runtime, dan inventaris.
   Simpan baseline. Aktifkan kolektor.
2. **Aktivasi mode.** Mode GitOps: pastikan `apps` dan `invenio-bootstrap`
   aktif dengan `automated` dan `selfHeal: true`. Mode imperatif: simpan `spec`
   Application asli yang tersanitasi, pause `apps` lebih dulu lalu
   `invenio-bootstrap` dengan merge patch `{"spec":{"syncPolicy":{"automated":null}}}`,
   dan verifikasi keduanya benar-benar berhenti.
3. **Injeksi.** Injektor menjalankan perintah injeksi tetap dan mencatat `t0`
   (kirim) serta `t_a` (respons API). Verifikasi bahwa bidang sasaran benar-benar
   berubah. Jangan menambah jeda buatan. Jika injeksi gagal atau tidak
   terverifikasi, tandai `invalid_injection` dan jangan menghitung waktu deteksi
   nol.
4. **Pengamatan.** Kolektor mengambil sampel pada interval nominal satu detik.
   `t_d` adalah sinyal deteksi pertama dari pemeriksa imperatif (mode imperatif)
   atau ArgoCD (mode GitOps); `t_e` adalah bukti tersimpan pertama yang
   mengidentifikasi objek dan bidang; `t_r` adalah pembacaan pertama seluruh
   inventaris dan bidang cocok, dikonfirmasi pada pembacaan berikutnya. Kolektor
   tidak memberi petunjuk dan tidak mengubah mekanisme koreksi.
5. **Pasca-run dan reset.** Ekspor bundel bukti, hitung SHA-256, catat status
   akhir, dan tutup `run_id`. Untuk mode imperatif, pulihkan `invenio-bootstrap`
   lalu `apps` ke nilai `automated` asli di `finally`, verifikasi, dan laporkan
   kegagalan restore sebagai `reset_failure`; Application tidak pernah dihapus.
   Ulangi seluruh pemeriksaan reset sebelum run berikutnya atau perpindahan mode.
   Jangan menyunting cap waktu setelah run.

## Field waktu

Semua waktu UTC dalam ISO 8601 dan waktu monotonik dalam detik dengan pecahan.
Durasi dihitung dari jam monotonik, bukan selisih UTC. Tidak ada interpolasi;
cap waktu adalah pengamatan pertama, bukan rekonstruksi setelah fakta.

| Field | Definisi | Produsen | Validasi |
|---|---|---|---|
| `run_id` | Identitas unik run | Kolektor | Sama pada semua berkas bukti |
| `arm` | `imperative` atau `gitops` | Runner | Hanya satu mode aktif |
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
| Versi runtime | Kubernetes, ArgoCD, CNPG, OpenSearch, MinIO, chart | Klaster dan snapshot | Bekukan sebelum run pertama |
| Status ArgoCD | `Application` status, sync operation, diff, event, dan kondisi | `kubectl -n argocd get application`, `argocd app get/diff` | Sanitasi; jangan sertakan token |
| Log perintah | Perintah injeksi/koreksi, waktu mulai/akhir, exit code, keluaran relevan | Runner dan runbook otomatis | Jangan sertakan Secret |
| Snapshot manifest | Objek sebelum dan sesudah, bidang terpilih | `kubectl get -o yaml` | Hapus `managedFields`, `resourceVersion`, status server, dan nilai Secret |
| Alert | Nama alert, `startsAt`, label, fingerprint | Alertmanager/Grafana | Jangan hanya menyalin teks pesan |
| HPA | Target, replika aktual, event, kondisi | `kubectl -n invenio get hpa -o yaml`, event | Terpisah dari R1 statis |
| Seed dan reset | ID draf, ukuran dan SHA-256 berkas, jumlah record/berkas, status antrean/index | Invenio dan `kubectl` | Seed tidak boleh diubah |
| Log kolektor | Interval aktual, jeda polling, kegagalan baca, versi kolektor | Kolektor | Di-hash setelah run |

Setiap berkas bukti memakai `run_id` yang sama. Berkas tanpa `run_id` atau
berasal dari run lain ditolak, bukan dianggap observasi run ini.

## Aturan atribusi pengendali

Atribusi dilakukan sebelum analisis, bukan setelah melihat hasil.

- **HPA.** Perubahan jumlah replika, status HPA, dan event scale adalah sinyal
  HPA. HPA adalah pemilik normal replika pada kedua mode. Pemulihan replika
  oleh HPA tidak dihitung sebagai deteksi atau pemulihan ArgoCD, dan tidak
  dihitung sebagai koreksi imperatif. `/spec/replicas` dikecualikan dari R1
  statis untuk Deployment yang dimiliki HPA; status HPA dilaporkan terpisah.
- **ArgoCD.** Deteksi dan pemulihan ArgoCD hanya dihitung untuk bidang terkelola
  pada skenario B--E yang benar-benar dipulihkan oleh rekonsiliasi.
  `OutOfSync` karena `/spec/replicas`, objek F di luar cakupan, atau perubahan
  yang dilakukan pengendali lain bukan bukti self-heal ArgoCD.
- **Pemeriksa imperatif.** Deteksi dan koreksi mode imperatif hanya dihitung
  untuk bidang terkelola pada skenario B--E yang benar-benar dijalankan oleh
  runbook. Sinyal HPA bukan deteksi imperatif.
- **Deployment controller.** Pembuatan ulang Pod atau rollout setelah Deployment
  berubah adalah konsekuensi, bukan pemulihan konfigurasi. Pemulihan dinilai dari
  kesetaraan inventaris dan bidang, bukan dari status rollout.
- **Pengendali lain.** SealedSecret, ImageUpdater, CNPG, Redis, OpenSearch, dan
  Velero tidak dihitung sebagai ArgoCD atau pemeriksa imperatif. Perubahan laten
  ImageUpdater dan SealedSecret harus dibekukan atau diisolasi sesuai kontrak
  yang disetujui.
- **Tidak pasti.** Jika pengendali tidak dapat dipastikan, isi `unattributed`
  dan keluarkan dari klaim efikasi ArgoCD maupun imperatif. Jangan menebak.

Skenario A dilaporkan sebagai kontrol HPA; F sebagai batas visibilitas objek
tak terkelola; G sebagai kasus deskriptif yang **bukan** kasus self-heal ArgoCD
(anotasi metadata dikembalikan oleh harness). Ketiganya tidak digabungkan ke
estimasi efikasi B--E.

## R3 tidak diukur

R3 (bukti keterlacakan) **tidak diukur** karena audit API server Kubernetes tidak
tersedia. Tanpa audit, pelaku mutasi out-of-band tidak dapat direkonstruksi untuk
kedua mode. R3 tidak dilaporkan sebagai nol, tidak dilaporkan sebagai tidak ada
perbedaan, dan tidak diuji secara statistik. Ketiadaan audit tidak menghambat
deployment atau pengukuran R1/R2; ia hanya menutup R3. Rekonstruksi pelaku,
objek/bidang, waktu/urutan, dan tindakan/hasil dibahas sebagai keterbatasan dan
pekerjaan lanjutan setelah audit diaktifkan.

## Kegagalan, penyensoran, dan validitas

- Injeksi yang gagal atau tidak terverifikasi adalah `invalid_injection`, bukan
  deteksi nol.
- Kegagalan pembacaan API atau kolektor adalah `instrumentation_failure`, bukan
  deteksi yang terlewat.
- Tidak ada sinyal sampai batas pengamatan adalah `right_censored` dengan batas
  waktu; waktu hilang tetap kosong.
- Pemulihan yang gagal atau reset yang gagal dicatat sebagai kegagalan, bukan
  dibuang agar hanya run sukses yang tersisa.
- Tidak ada waktu reaksi manusia yang diukur; kedua mode berjalan otomatis.
  Resolusi kolektor serta interval pemeriksa imperatif dan rekonsiliasi ArgoCD
  membatasi ketepatan waktu.
- Mode dijalankan berurutan pada satu stack, sehingga kondisi klaster antarblok
  dapat berbeda dan perlakuan tidak terisolasi. Urutan mode diacak, kondisi
  dicatat, dan reset diverifikasi; perbedaan waktu dan beban latar tidak
  dianggap tereliminasi.
- Satu stack, satu kolektor, satu implementasi otomasi imperatif, dan satu
  implementasi ArgoCD membatasi generalisasi. Studi ini adalah studi kasus
  tunggal; replikasi dengan konfigurasi berbeda dianjurkan, bukan diklaim oleh
  dokumen ini.
- Diff atau `t_e` hanya menunjukkan deviasi, bukan penyebab kausal.

## Larangan

Dokumen ini tidak memberikan izin untuk:

- menjalankan injeksi, polling, pemulihan, atau reset pada klaster;
- menyentuh namespace `argocd`, `database`, `monitoring`, `velero`, atau objek
  bersama; pada namespace `invenio`, hanya objek yang tercantum dalam kontrak
  bidang skenario yang boleh disentuh;
- membaca, menyalin, atau menerbitkan nilai Secret;
- melakukan restore, purge queue/data, migrasi, deploy, atau perubahan
  pengendali di luar prosedur penjedaan/pemulihan ArgoCD yang disetujui;
- mengarang cap waktu, status, atau hasil yang tidak teramati.

Jika terjadi pelanggaran keselamatan atau kondisi tak terduga, hentikan run,
catat waktunya, dan tandai run sebagai gagal. Jangan melanjutkan ke run berikutnya
sebelum reset lengkap terverifikasi.

## Instrumen live

Protokol ini diimplementasikan sebagai harness di [`live/README.md`](live/README.md).
Harness berjalan dry-run secara default, memakai `kubectl` tanpa shell, dan
menargetkan stack InvenioRDM nyata. Dokumen protokol ini yang mengikat untuk
desain satu stack, rencana 210 run, dan batas R3; rincian mekanis harness tetap
berlaku sepanjang tidak bertentangan dengan protokol ini.

## Rujukan

- `content/proposal/chapters/bab3-metodologi.tex` — definisi R1/R2, HPA, dan
  gerbang baseline.
- `content/skripsi/chapters/bab3-metodologi.tex` — protokol dan ancaman
  validitas versi skripsi.
- `experiments/README.md` — kontrak bukti dan instrumen offline.
- `experiments/live/README.md` — harness live dry-run default dan rincian
  mekanis.
- `experiments/deployment-source.json` — sumber deployment yang diperiksa.
- `invenio-rdm-gitops/docs/current-state.md` — snapshot lingkungan 25 Oktober
  2026 dan gerbang kesiapan.
