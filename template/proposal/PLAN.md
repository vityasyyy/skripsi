
# PLAN.md

# Rencana Eksekusi Tugas Akhir

## Judul Tugas Akhir

Evaluasi GitOps terhadap Penurunan Configuration Drift pada Deployment Multi-Service di Klaster Kubernetes: Studi Kasus InvenioRDM

---

# 1. Tujuan Penelitian

Penelitian ini mengevaluasi secara empiris apakah manajemen deployment berbasis GitOps menggunakan ArgoCD dapat mengurangi keseluruhan konsistensi operasional (*operational inconsistency*) dan *configuration drift* akibat intervensi manusia pada lingkungan Kubernetes, dibandingkan dengan alur kerja deployment manual konvensional menggunakan *kubectl*.

Fokus penelitian meliputi:

* konsistensi deployment,
* jejak audit operasional (*operational traceability*),
* pemulihan drift (*drift recovery*),
* pengurangan intervensi manual,
* dan keandalan alur kerja (*workflow reliability*).

Tesis ini merupakan **studieksperimental kuantitatif**, BUKAN proposal kerangka orkestrasi baru.

Implementasi infrastruktur hanya berfungsi sebagai **apparatus ekperimental** untuk pengukuran dan evaluasi.

---

# 2. Masalah Inti Penelitian

Operasi manual pada Kubernetes sering menimbulkan *configuration drift* karena:

* *kubectl edit* langsung pada klaster,
* perubahan yang tidak didokumentasikan,
* prosedur deployment yang tidak konsisten,
* kesalahan operasional manusia,
* dan kurangnya jejak audit terpusat untuk perubahan deployment.

Masalah-masalah ini menimbulkan:

* inkonsistensi deployment,
* prosedur *rollback* yang sulit,
* auditabilitas yang buruk,
* dan peningkatan waktu pemulihan operasional.

Penelitian ini mengevaluasi apakah praktik GitOps memperbaiki karakteristik operasional tersebut.

---

# 3. Jenis Penelitian

**Studi Kuasi-Eksperimen** (*Quasi-Experimental Study*)

Penelitian ini dipilih sebagai studi kuasi-eksperimen karena subjek (klaster Kubernetes dan workload) tidak dapat dirandomisasi secara penuh, namun kondisi perlakuan (pendekatan deployment) dapat dikendalikan dan diacak urutannya. Desain ini memungkinkan perbandingan kausal yang kuat tanpa menuntut randomisasi lengkap pada unit-unit eksperimental, sesuai dengan konteks riset sistem terdistribusi.

Penelitian akan:

* membangun lingkungan deployment yang terkontrol,
* secara sengaja memasukkan skenario drift,
* mengumpulkan metrik operasional,
* membandingkan pendekatan manajemen deployment,
* dan menganalisis perilaku yang dihasilkan.

---

# 3.1. Rancangan Eksperimental

Desain kuasi-eksperimen menggunakan format **pre-test -- treatment -- post-test** pada dua kelompok paralel:

| Tahap | Lingkungan A (Manual) | Lingkungan B (GitOps) |
|---|---|---|
| **O1** (Pra-uji) | Ukur baseline deployment bersih | Ukur baseline deployment bersih |
| **X** (Perlakuan) | Injeksi drift manual (kubectl) | Injeksi drift manual (kubectl) |
| **O2** (Pasca-uji) | Ukur: recovery time, intervensi, konsistensi, traceability | Ukur: detection time, self-heal, recovery time, konsistensi, traceability |

Keterangan:
* **O1/O2** = Observasi/Pengukuran
* **X** = Perlakuan (treatment): injeksi controlled drift

---

# 4. Perbandingan Eksperimental

## Lingkungan A -- Deployment Manual

Alur kerja deployment:

* kubectl apply
* manual scaling
* manual patching
* modifikasi langsung pada klaster

Karakteristik:

* *state* klaster yang dapat berubah (*mutable cluster state*)
* jejak audit rendah (*low traceability*)
* ketergantungan operasional pada prosedur manusia

---

## Lingkungan B -- Deployment GitOps

Alur kerja deployment:

* Git sebagai sumber kebenaran tunggal
* Rekonsiliasi ArgoCD
* Manifest deklaratif
* Helm/Kustomize templating (opsional)

Karakteristik:

* rekonsiliasi deklaratif
* koreksi drift otomatis
* jejak audit deployment
* *desired state* yang terpusat

---

# 5. Ruang Lingkup Infrastruktur

## Lingkungan Kubernetes

Klaster:

* 3 node
* 24 total inti CPU
* ~23 Gi total memori
* Klaster Kubernetes yang dikelola Rancher

---

## Beban Kerja (Workload)

Beban kerja utama:

* Deployment InvenioRDM

Beban kerja harus tetap realistis dan tidak sepele:

* banyak layanan (*multiple services*),
* ingress,
* komponen persisten,
* dependensi konfigurasi.

InvenioRDM adalah **target deployment**, BUKAN fokus penelitian.

---

# 6. Tumpukan Teknologi (Technology Stack)

## Wajib

* Kubernetes
* ArgoCD
* GitHub
* kubectl
* Helm
* Kustomize

---

## Opsional

* GitHub Actions
* Terraform (hanya jika diperlukan untuk *provisioning* infrastruktur eksternal)

Terraform tidak boleh menjadi subjek penelitian utama.

---

# 7. Variabel Penelitian

## Variabel Independen (Variabel Bebas)

Pendekatan manajemen deployment:

* alur kerja manual *kubectl*
* alur kerja GitOps menggunakan ArgoCD

---

## Variabel Dependen (Variabel Terikat)

### Metrik Utama

**Konsistensi Deployment (R1)**

Definisi:
Persentase sumber daya klaster yang cocok dengan *desired declarative state* setelah operasi deployment dan skenario drift.

Kemungkinan pengukuran:

* jumlah sumber daya yang mengalami drift,
* rasio keberhasilan rekonsiliasi,
* persentase kepatuhan terhadap *desired state*.

Cara ukur:
Hitung jumlah pod/deployment/configmap yang statusnya "Synced/Healthy" dibagi total sumber daya yang diharapkan, untuk kedua lingkungan.

---

### Metrik Sekunder

## Waktu Pemulihan Drift (R2)

Definisi:
Waktu yang dibutuhkan untuk mengembalikan *state* klaster ke konfigurasi deklaratif yang dimaksud setelah modifikasi tidak sah.

Cara ukur:
* Lingkungan B: $(t_2 - t_0)$, di mana $t_0$ = waktu injeksi drift, $t_2$ = waktu ArgoCD selesai self-heal
* Lingkungan A: $(t_2 - t_0)$, di mana operator mengeksekusi `kubectl` secara manual untuk memulihkan *state*

---

## Jumlah Intervensi Manual (R3)

Definisi:
Jumlah operasi korektif manual yang diperlukan setelah insiden drift.

Contoh:

* kubectl edit
* kubectl rollout restart
* penghapusan pod manual
* tindakan rekonsiliasi manual

Cara ukur:
Catat setiap perintah `kubectl` yang dieksekusi oleh operator setelah drift untuk Lingkungan A. Untuk Lingkungan B, catat jumlah `argocd app sync` manual yang diperlukan (self-heal dinonaktifkan untuk baseline pengukuran R3, atau dihitung intervensi manual tambahan jika self-heal gagal).

---

## Tingkat Kegagalan (R4)

Definisi:
Persentase operasi deployment atau rekonsiliasi yang gagal memulihkan *state* klaster yang dimaksud.

---

## Jejak Audit Operasional / Traceability (R5)

Definisi:
Kemampuan mengidentifikasi:

* siapa yang mengubah *state* deployment,
* apa yang berubah,
* kapan perubahan terjadi,
* dan bagaimana pemulihan dilakukan.

Metrik dapat dijadikan kuantitatif sebagai berikut:

* **Skor Rubrik Traceability (1--5):** Untuk setiap skenario drift, dinilai berdasarkan 4 aspek: identifikasi *who/what/when/how*. Skor 5 = seluruh aspek dapat dipastikan. Skor 1 = tidak ada jejak yang dapat direkonstruksi.
* **Mean Time To Identify Drift (MTTI):** Waktu dari drift terjadi hingga drift terdeteksi dan teridentifikasi (Lingkungan B: notifikasi ArgoCD; Lingkungan A: audit log + `kubectl get`).
* **Kelengkapan Audit Log:** Persentase perubahan yang dapat direkonstruksi dari Git history (Lingkungan B) dibandingkan dengan Kubernetes audit logs (Lingkungan A).

---

# 8. Skenario Drift

Eksperimen harus secara sengaja memasukkan kondisi drift terkontrol.

## Skenario Drift Terencana

### Skenario A -- Perubahan Replika (*Replica Drift*)

Secara manual mengubah jumlah replika Deployment.

Contoh:
kubectl scale deployment

---

### Skenario B -- Perubahan Image (*Image Drift*)

Secara manual mengganti versi image kontainer.

Contoh:
kubectl edit deployment

---

### Skenario C -- Perubahan ConfigMap (*ConfigMap Drift*)

Mengubah isi ConfigMap langsung di dalam klaster.

---

### Skenario D -- Penghapusan Sumber Daya (*Resource Deletion*)

Menghapus deployment/service secara manual.

Contoh:
kubectl delete deployment

**Catatan ArgoCD:** Ketika `syncPolicy.automated.prune` diaktifkan, ArgoCD akan mendeteksi sumber daya yang hilang dan menciptakan ulang dari Git. Hal ini harus didokumentasikan sebagai perilaku yang diharapkan.

---

### Skenario E -- Patch Manual Tidak Sah (*Unauthorized Manual Patch*)

Menerapkan *kubectl patch* langsung terhadap sumber daya yang dikelola.

---

### Skenario F -- Drift Lintas Namespace (*Cross-namespace Drift*)

Menerapkan sumber daya ke namespace yang salah secara manual. Mengukur apakah GitOps membatasi propagasi atau mendeteksi kesalahan namespace secara otomatis.

Contoh:
`kubectl apply -f deployment.yaml --namespace=wrong-namespace`

---

### Skenario G -- Perubahan Secret (*Secret Drift*)

Mengubah secret secara manual di luar Git. Skenario ini sangat umum dalam praktik produksi dan menantang karena secret sering dirotasi secara manual.

Contoh:
`kubectl patch secret my-secret --patch='{"data":{"password":"<new-base64>"}}'`

---

# 9. Prosedur Eksperimental

Untuk setiap skenario drift:

1. Deploy beban kerja baseline
2. Verifikasi *state* klaster yang sehat
3. Ukur **O1** (observasi pra-uji / baseline bersih)
4. Injeksi drift secara manual
5. Catat **$t_0$** (timestamp drift)
6. Ukur **O2** (observasi pasca-uji):

   * perilaku deteksi drift,
   * perilaku pemulihan,
   * tindakan operasional yang diperlukan,
   * konsistensi deployment,
   * durasi pemulihan ($t_2 - t_0$)
7. Ulangi sebanyak **n = 5** kali per skenario per lingkungan (minimum). Untuk **Waktu Pemulihan Drift (R2)**, ulangi sebanyak **n = 10** kali untuk meningkatkan granularitas statistik.
8. Ulangi untuk:

   * alur kerja deployment manual
   * alur kerja GitOps
9. Bandingkan hasil

**Pengacakan Kondisi:** Untuk memitigasi efek urutan, urutan penerapan skenario drift pada setiap lingkungan diacak menggunakan daftar acak (*randomized block*).

---

# 10. Kontrol Variabel Pengganggu (Controlling Confounding Variables)

Agar validitas internal tetap tinggi, variabel berikut harus dikendalikan:

1. **Interval Sinkronisasi ArgoCD:** Ditetapkan pada 60 detik (bukan default 180 detik) agar waktu deteksi konsisten.
2. **Tekanan Sumber Daya Node:** Rekam penggunaan CPU/memori klaster sebelum setiap pengujian. Hanya jalankan eksperimen jika node berada di bawah 70% kapasitas.
3. **Latensi Jaringan:** Gunakan klaster *on-premise* dengan latensi stabil. Catat RTT antar-node.
4. **Waktu Injeksi Drift:** Injeksi selalu dilakukan pada interval sinkronisasi ArgoCD untuk menghindari *edge case* waktu tunggu yang tidak dapat diprediksi.
5. **Versi ArgoCD:** Gunakan satu versi ArgoCD (v2.12+) sepanjang eksperimen.

---

# 11. Pengumpulan Data

## Data Kuantitatif

Contoh:

* waktu pemulihan
* tingkat keberhasilan deployment
* jumlah intervensi manual
* durasi rekonsiliasi
* jumlah sumber daya yang tidak konsisten
* skor rubrik traceability
* MTTI (Mean Time To Identify Drift)

---

## Observasi Kualitatif

Contoh:

* kompleksitas operasional
* auditabilitas
* kejelasan *rollback*
* jejak perubahan deployment

Observasi kualitatif harus mendukung temuan kuantitatif, bukan menggantikannya.

---

# 12. Analisis Statistik

## Uji Normalitas

Sebelum uji parametrik, terapkan **Shapiro-Wilk test** pada setiap metrik untuk memeriksa normalitas distribusi.

## Uji Hipotesis

* **Jika data terdistribusi normal:** Gunakan *paired t-test* untuk membandingkan rata-rata metrik antar-kondisi (A vs B).
* **Jika data tidak terdistribusi normal:** Gunakan *Wilcoxon signed-rank test* (non-parametrik).
* **Ukuran efek:** Hitung Cohen's $d$ (untuk paired t-test) atau Cliff's delta (untuk Wilcoxon) untuk mengukur signifikansi praktis.

---

# 13. Strategi Tinjauan Pustaka

Tinjauan pustaka harus berfokus pada:

* model operasional GitOps
* *configuration drift* pada Kubernetes
* konsistensi deployment
* rekonsiliasi infrastruktur
* keandalan DevOps
* manajemen infrastruktur deklaratif

Hindari:

* tutorial Kubernetes generik
* tulisan blog yang murni berfokus pada implementasi
* materi pemasaran vendor

---

# 14. Alur Kerja Tinjauan Pustaka Awal

## Fase 1 -- Makalah Survei

Baca:

* makalah tinjauan GitOps
* makalah operasi Kubernetes
* studi keandalan DevOps

Tujuan:
memahami terminologi, metrik, dan metodologi umum.

---

## Fase 2 -- Makalah Empiris

Fokus pada:

* desain eksperimental,
* pemilihan metrik,
* metode perbandingan,
* pendekatan analisis data.

Bangun matriks literatur:

| Paper | Masalah | Metode | Metrik | Kelemahan |
| ----- | ------- | ------ | ------- | -------- |

---

# 15. Kendala Penting

## Hindari Ledakan Ruang Lingkup (Scope Explosion)

Tesis ini BUKAN tentang:

* membangun platform,
* menemukan orkestrator baru,
* membuat kerangka CI/CD baru,
* atau *benchmarking* klaster Kubernetes skala hyperscale.

Tetap fokus sempit:
mitigasi *configuration drift* dan keandalan operasional.

---

## Hindari Arsitektur Terlalu Kompleks

Implementasi harus dioptimalkan untuk:

* reprodusibilitas,
* observabilitas,
* pengukuran,
* eksperimen terkontrol,
* dan konsistensi deployment.

BUKAN untuk:

* kekayaan fitur,
* lapisan abstraksi,
* atau kompleksitas otomatisasi yang berlebihan.

---

## Analisis Risiko

Potensi risiko dan mitigasinya:

1. **InvenioRDM gagal di-deploy:**
   Mitigasi: Siapkan *fallback workload* yang lebih sederhana (mis. aplikasi *microservice* multi-kontainer seperti *Online Boutique* atau *Sock Shop*).

2. **ArgoCD gagal merekonsiliasi suatu tipe sumber daya:**
   Mitigasi: Dokumentasikan sebagai temuan kualitatif (keterbatasan alat, bukan kegagalan eksperimen).

3. **Klaster tidak tersedia di tengah eksperimen:**
   Mitigasi: Semua manifest dan prosedur tersimpan dalam repositori Git yang terversion; lingkungan dapat direkonstruksi dalam hitungan menit.

---

# 16. Deliverables

## Deliverables Infrastruktur

* lingkungan deployment Kubernetes (dua konfigurasi)
* *pipeline* deployment GitOps
* manifest yang dapat direproduksi
* prosedur injeksi drift
* *script* eksperimen otomatis

---

## Deliverables Penelitian

* tinjauan pustaka
* bab metodologi
* dataset eksperimental
* analisis metrik
* interpretasi hasil
* analisis perbandingan operasional

---

# 17. Langkah Selanjutnya yang Prioritas

## Prioritas 1

Buat:

* pertanyaan penelitian,
* hipotesis (H0 dan H1 formal),
* definisi metrik,
* matriks eksperimental.

---

## Prioritas 2

Bangun:

* repositori deployment yang dapat direproduksi,
* konfigurasi ArgoCD (Lingkungan B),
* alur kerja manual baseline (Lingkungan A).

---

## Prioritas 3

Buat:

* *script* injeksi drift,
* prosedur pengukuran,
* strategi logging.

---

## Prioritas 4

Mulai tinjauan pustaka dan pelaksanaan eksperimen secara paralel.

---

# 18. Pertanyaan Penelitian yang Diusulkan

**RQ1:** Bagaimana tingkat konsistensi deployment pada lingkungan GitOps (ArgoCD) dibandingkan dengan lingkungan deployment manual (kubectl) setelah diberikan skenario *configuration drift*?

**RQ2:** Berapa lama waktu yang dibutuhkan untuk mendeteksi dan memulihkan *configuration drift* pada lingkungan GitOps dibandingkan dengan lingkungan manual?

**RQ3:** Berapa banyak intervensi manual yang diperlukan untuk memulihkan *state* klaster setelah insiden drift pada masing-masing lingkungan?

**RQ4:** Bagaimana tingkat jejak audit (*traceability*) dan auditabilitas deployment pada lingkungan GitOps dibandingkan dengan lingkungan manual?

---

# 19. Hipotesis yang Diusulkan

## Hipotesis Nol (H0)

Tidak terdapat perbedaan yang signifikan secara statistik antara pendekatan deployment GitOps (ArgoCD) dan pendekatan deployment manual (kubectl) pada metrik: konsistensi deployment, waktu pemulihan drift, jumlah intervensi manual, dan tingkat jejak audit.

## Hipotesis Alternatif (H1)

Pendekatan deployment GitOps (ArgoCD) secara signifikan meningkatkan konsistensi deployment, mengurangi waktu pemulihan drift, menurunkan jumlah intervensi manual, dan meningkatkan tingkat jejak audit (*traceability*) dibandingkan dengan pendekatan deployment manual (kubectl).

---

# 20. Pemetaan Rencana terhadap Bab Proposal

| Bagian Rencana | Bab Proposal UGM | Judul Bab |
|---|---|---|
| Pertanyaan Penelitian & Hipotesis | Bab I | Rumusan Masalah & Hipotesis |
| Strategi Tinjauan Pustaka | Bab II | Penelitian Terkait |
| Variabel & Metrik | Bab III | Metode dan Rancangan Penelitian |
| Skenario Drift & Prosedur | Bab III | Metode dan Rancangan Penelitian |
| Pengumpulan Data & Analisis | Bab III | Metode dan Rancangan Penelitian |
| Jadwal | Bab IV | Jadwal Penelitian |

---

# 21. Jadwal Penelitian (Gantt Chart Berbasis Bulan)

| Fase | Bulan 1 | Bulan 2 | Bulan 3 | Bulan 4 | Bulan 5 | Bulan 6 | Bulan 7 | Bulan 8 |
|---|---|---|---|---|---|---|---|---|
| Studi Literatur | $\bullet$ | $\bullet$ | | | | | | |
| Perancangan Lingkungan | | $\bullet$ | $\bullet$ | | | | | |
| Implementasi ArgoCD + Baseline Manual | | | $\bullet$ | $\bullet$ | | | | |
| Persiapan Baseline & Kalibrasi | | | | $\bullet$ | $\bullet$ | | | |
| Eksperimen & Pengumpulan Data (E1--E4) | | | | | $\bullet$ | $\bullet$ | | |
| Analisis Statistik & Interpretasi | | | | | | $\bullet$ | $\bullet$ | |
| Penulisan Laporan | $\bullet$ | $\bullet$ | $\bullet$ | $\bullet$ | $\bullet$ | $\bullet$ | $\bullet$ | $\bullet$ |
| Seminar / Sidang | | | | | | | | $\bullet$ |

Keterangan: 8 bulan. Penulisan laporan dilakukan paralel sepanjang penelitian.
