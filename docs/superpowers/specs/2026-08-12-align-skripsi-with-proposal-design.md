# Design: Align Skripsi dan Repo dengan Proposal yang Diterima

**Tanggal:** 2026-08-12
**Status:** Disetujui oleh user
**Sumber kebenaran:** `content/proposal/` (proposal sudah diterima dan direview dosen pembimbing)

---

## 1. Konteks dan Masalah

Proposal Tugas Akhir sudah diterima dan direview dosen. Proposal tersebut adalah **studi kuasi-eksperimen** (perbandingan deployment manual `kubectl` vs GitOps/ArgoCD terhadap configuration drift pada Kubernetes), BUKAN inovasi produk. Namun:

- `content/skripsi/` masih skeleton template kosong: metadata placeholder (`NAMA LENGKAP`, `JUDUL BAHASA INDONESIA`), intisari/abstract lorem ipsum, 6 bab kosong berstruktur "Inovasi Produk" (Bab 2 Identifikasi Masalah & Ide Inovatif, Bab 4 Perancangan Prototipe/Produk, Bab 5 Proses Pembuatan Produk, Bab 6 Pengujian & Evaluasi Produk), 1 referensi placeholder, lampiran kosong.
- AGENTS.md dan README.md masih mendeskripsikan skripsi sebagai "Inovasi Produk" dengan struktur 6 bab.
- CI workflow memiliki job `compile-skripsi` yang dinonaktifkan (`if: false`).
- Proposal berisi 30 referensi, 3 diagram TikZ, metadata lengkap yang belum tersalin ke skripsi.

Tujuan: menyelaraskan seluruh repo (skripsi LaTeX + dokumen repo) agar proposal yang diterima menjadi satu-satunya sumber kebenaran.

## 2. Keputusan Kunci (dari sesi brainstorming)

1. **Struktur skripsi:** Struktur penelitian empiris 5 bab (BUKAN Inovasi Produk 6 bab), karena proposal adalah studi kuasi-eksperimen.
2. **Format mengikuti contoh:** Gunakan format dari `examples/skripsi/contoh_skripsi.pdf` dan `examples/proposal/contoh_proposal.pdf` (konvensi halaman awal, penomoran `1.1.`, format INTISARI/ABSTRACT, format sitasi (Author, Year), gaya tabel/gambar), namun struktur bab tetap empiris 5 bab.
3. **Strategi porting:** Pendekatan A — port setia (verbatim) konten proposal Bab 1-3 ke skripsi, hanya reframe kalimat "penelitian yang diuraikan dalam proposal ini" → "penelitian ini" dan hapus bagian khusus proposal (Sistematika Penulisan proposal → diperbarui untuk 5 bab skripsi).
4. **Kedalaman konten:** Bab 1-3 diisi penuh dari proposal; Bab 4-5 berupa outline terstruktur dengan TODO (eksperimen belum berjalan — jadwal Sep-Okt 2026).
5. **Ruang lingkup:** Hanya LaTeX + dokumentasi repo (AGENTS.md, README, CI, Makefile). TIDAK membuat scaffolding kode eksperimen (drift-inject.sh dll.) — itu deliverable penelitian di masa depan.

## 3. Struktur Skripsi Target

| Bab | Judul | Isi |
|-----|-------|-----|
| Bab 1 | PENDAHULUAN | Latar Belakang, Rumusan Masalah, Batasan Masalah, Tujuan Penelitian, Manfaat Penelitian, Sistematika Penulisan (diperbarui untuk 5 bab) |
| Bab 2 | TINJAUAN PUSTAKA | Port setia Bab 2 proposal (Penelitian Terkait) |
| Bab 3 | METODE PENELITIAN | Port setia Bab 3 proposal (Metode dan Rancangan Penelitian) |
| Bab 4 | HASIL DAN ANALISIS | Outline terstruktur: lingkungan eksperimen, hasil R1/R2/R3, statistik deskriptif, uji Mann–Whitney U, ukuran efek, interpretasi, pembahasan — TODO |
| Bab 5 | KESIMPULAN DAN SARAN | Outline: kesimpulan per RQ, saran, keterbatasan — TODO |

## 4. Perubahan per Berkas

### 4.1 `content/skripsi/main.tex`

- **Metadata** (salin dari `content/proposal/main.tex`):
  - `\titleind{Perbandingan Terkontrol Paradigma \textit{Deployment} Manual dan GitOps dalam Menghadapi Penyimpangan Konfigurasi pada Klaster Kubernetes}`
  - `\titleeng{A Controlled Comparison of Manual and GitOps Deployment Paradigms in Responding to Configuration Drift on Kubernetes Clusters}`
  - `\fullname{Muhammad Argya Vityasy}`, `\idnum{23/522547/PA/22475}`, `\degree{Sarjana}`, `\gelar{S.Kom.}`, `\yearsubmit{2026}`, `\program{Ilmu Komputer}`, `\dept{Ilmu Komputer dan Elektronika}`
  - `\firstsupervisor{Guntur Budi Herwanto, S.Kom., M.Cs.}`, `\firstexaminer{Dr. techn. Kabul Kurniawan, S.Kom., M.Cs.}`, `\secondexaminer{Aina Musdholifah, S.Kom., M.Kom., Ph.D.}`, `\examdate{17 Juni 2026}`
- **Preamble**: selaraskan dengan proposal — tambah `tikz` + `\usetikzlibrary{shapes.geometric,arrows.meta,positioning,fit,backgrounds,calc}`, `xurl`, `\graphicspath{{figures/}{diagrams/}}`. Pertahankan lstdefinitions yaml/docker/bash.
- **Halaman awal**: pertahankan urutan template — cover → titlepageind → approvalpage → declarepage → motto → acknowledment → preface → tableofcontents → listoftables → listoffigures → lambang → abstractind → abstracteng.
  - Catatan: contoh skripsi tidak memiliki motto/persembahan, namun AGENTS.md (berbasis pedoman) mewajibkannya → tetap dipertahankan.
  - Intisari/Abstract: draft nyata dari abstrak proposal (Indonesia + Inggris), bagian hasil ditandai TODO (eksperimen belum berjalan).
- **Daftar Simbol** (`\lambang`): isi dengan singkatan kunci tesis: GitOps, IaC, ArgoCD, R1 (konsistensi deployment), R2 (waktu deteksi/pemulihan/identifikasi akar masalah), R3 (traceability), MTTI, NASA-TLX, dsb.
- **Include bab**: `bab1-pendahuluan`, `bab2-tinjauan-pustaka`, `bab3-metodologi`, `bab4-hasil-analisis`, `bab5-kesimpulan-saran`.

### 4.2 Bab-bab (`content/skripsi/chapters/`)

| Aksi | Berkas |
|------|--------|
| Port (bab1-pendahuluan.tex ditimpa) | Proposal bab1 → "PENDAHULUAN": Latar Belakang, Rumusan Masalah, Batasan Masalah, Tujuan, Manfaat, Sistematika Penulisan (update 5 bab) |
| Rename + port | `bab2-identifikasi-masalah.tex` → `bab2-tinjauan-pustaka.tex` (judul "TINJAUAN PUSTAKA"), isi = proposal bab2 verbatim |
| Rename + port | `bab3-kajian-ilmiah.tex` → `bab3-metodologi.tex` (judul "METODE PENELITIAN"), isi = proposal bab3 verbatim |
| Tulis baru | `bab4-hasil-analisis.tex` — outline: Deskripsi Lingkungan Eksperimen, Hasil E1 (R1 konsistensi), Hasil E2 (R2 waktu), Hasil E3 (R3 traceability), Statistik Deskriptif, Uji Mann–Whitney U, Ukuran Efek, Interpretasi, Pembahasan — semua TODO |
| Tulis baru | `bab5-kesimpulan-saran.tex` — outline: Kesimpulan per RQ, Saran, Keterbatasan — TODO |
| Hapus | `bab4-perancangan.tex`, `bab5-pembuatan.tex`, `bab6-pengujian.tex` |

Reframe porting: ganti "penelitian yang diuraikan dalam proposal ini" → "penelitian ini"; hapus bagian yang hanya berlaku untuk proposal (mis. deskripsi Bab IV Jadwal di Sistematika Penulisan). Gambar dari proposal (`fig:arsitektur-eksperimen`, `fig:drift-scenarios`, `fig:bagan-alir-eksperimen`) disertakan di Bab 3 dengan label/caption yang sama.

### 4.3 `content/skripsi/references.bib`

Ganti placeholder dengan 30 entri dari `content/proposal/references.bib` (salin verbatim).

### 4.4 Gambar dan diagram

- Buat `content/skripsi/diagrams/`; salin dari `content/proposal/diagrams/`: `architecture-overview.pdf`, `drift-scenarios.pdf`, `experiment-flow.pdf`, dan folder `logos/`.
- `figures/logougm.png` sudah ada — pertahankan.

### 4.5 `content/skripsi/lampiran/lampiran-a.tex`

Outline sesuai deliverable proposal:
- Kode sumber: skrip eksperimen (`drift-inject.sh`, `metrics-collect.sh`, `baseline-check.sh`, `recovery-runbook.sh`) — listing placeholder
- Konfigurasi: manifest Kubernetes, konfigurasi ArgoCD (sync policy, self-heal, prune), Helm/Kustomize — listing placeholder
- Dataset: skema log JSON/CSV (t0, td, trci, t2), snapshot klaster — placeholder

### 4.6 `AGENTS.md`

- Bagian "Jenis TA": ubah dari "Skripsi Inovasi Produk" → **Studi Empiris (Kuasi-Eksperimen)**: membandingkan deployment manual vs GitOps terhadap configuration drift.
- "Struktur SKRIPSI": ganti tabel 6 bab Inovasi Produk → 5 bab empiris (tabel di atas).
- "Perbedaan Kunci": perbarui baris struktur skripsi.
- Jaga agar panduan lain (sitasi, gambar, kompilasi) tetap.

### 4.7 `README.md`

- Perbarui struktur repo (bab skripsi 5 file, lampiran).
- Pertahankan judul/topik (sudah sesuai), perbarui deskripsi jika ada referensi ke "6 bab".

### 4.8 `.github/workflows/compile-latex.yml`

- Aktifkan job `compile-skripsi`: hapus `if: false`.
- Tambahkan `content/skripsi/**` ke daftar `paths` trigger (push & pull_request).
- Tambahkan skripsi PDF ke artifact dan release files.

### 4.9 `Makefile`

Tidak ada perubahan target yang diperlukan (target `skripsi` dan `skripsi-docker` sudah ada). Hanya verifikasi `clean-skripsi` tetap berfungsi.

## 5. Verifikasi

1. `make proposal` berhasil dikompilasi (tidak boleh rusak — proposal adalah sumber kebenaran).
2. `make skripsi` berhasil dikompilasi (pdflatex + bibtex + 2x pdflatex) tanpa error.
3. Cek semua `\citep`/`\citet` ter-resolve (tidak ada `[?]` di output).
4. Cek label gambar/tabel ter-resolve, tidak ada "??" di output.
5. CI lokal tidak dijalankan; workflow diverifikasi secara statis.

## 6. Di Luar Ruang Lingkup (explicitly excluded)

- Membuat kode eksperimen (skrip otomasi, manifest GitOps) — deliverable penelitian masa depan.
- Mengubah konten proposal yang sudah diterima.
- Mengubah `presentation/` (presentasi proposal sudah selaras dengan proposal).
- Mengubah `bimbingan-snapshots/` (dokumentasi historis).
- Mengisi hasil eksperimen nyata Bab 4-5 (data belum ada — jadwal eksperimen Sep-Okt 2026).
