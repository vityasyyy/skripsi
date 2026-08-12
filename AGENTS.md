# AGENTS.md — Pedoman dan Referensi Penulisan Skripsi UGM

> **Panduan resmi:** `@examples/pedoman_ta.pdf`  
> **Contoh Proposal:** `@examples/contoh_proposal.pdf`  
> **Contoh Skripsi:** `@examples/contoh_skripsi.pdf`

---

## Aturan Prioritas (WAJIB DIKUTI)

1. **Pedoman (`pedoman_ta.pdf`) adalah prioritas UTAMA**
2. Jika ada perbedaan antara pedoman dan contoh PDF, **ikuti pedoman**
3. Contoh PDF hanya sebagai referensi format/visual, bukan aturan

---

## Jenis TA: Skripsi Studi Empiris (Kuasi-Eksperimen)

Mahasiswa melakukan studi empiris terkontrol: **evaluasi perbandingan deployment manual (`kubectl`) vs GitOps (ArgoCD) terhadap configuration drift pada klaster Kubernetes** (studi kasus workload multi-service InvenioRDM). Implementasi infrastruktur hanya berfungsi sebagai **apparatus eksperimental** untuk pengukuran, bukan produk yang dikembangkan.

---

## Struktur PROPOSAL (`proposal/`)

> Class: `\documentclass[proposal,indonesia]{ugmskripsi}`

### Bagian Awal
| Elemen | Ada? | Keterangan |
|--------|------|-----------|
| Halaman Sampul | ✅ | "PROPOSAL TUGAS AKHIR" |
| Halaman Pengesahan | ✅ | Wajib ada, muncul di Daftar Isi |
| Daftar Isi | ✅ | Hanya Daftar Isi |
| Intisari | ✅ | Bahasa Indonesia saja |
| Abstract | ✅ | Contoh memiliki, pedoman tidak menyebut — ikuti contoh |

### Bagian Utama
| Bab | Judul | Isi |
|-----|-------|-----|
| **Bab 1** | Pendahuluan | Latar Belakang, **Rumusan Masalah**, Batasan Masalah, Tujuan Penelitian, Manfaat Penelitian |
| **Bab 2** | Penelitian Terkait | State of the art, literatur review |
| **Bab 3** | Metode dan Rancangan Penelitian | Deskripsi umum, metodologi, bagan alir, perancangan sistem |
| **Bab 4** | Jadwal Penelitian | Gantt Chart berbasis bulan |

### Bagian Akhir
| Elemen | Ada? |
|--------|------|
| Glosarium | ⚠️ Opsional — hanya jika ada jargon teknis yang membingungkan |
| Daftar Pustaka | ✅ |

### Yang TIDAK ADA di Proposal
- ❌ Halaman Pernyataan (Declaration)
- ❌ Motto
- ❌ Persembahan (Acknowledgment)
- ❌ Prakata (Preface)
- ❌ Daftar Tabel
- ❌ Daftar Gambar
- ❌ Daftar Lambang/Simbol
- ❌ Lampiran

---

## Struktur SKRIPSI (`skripsi/`)

> Class: `\documentclass[skripsi,indonesia]{ugmskripsi}`

### Bagian Awal
| Elemen | Ada? | Keterangan |
|--------|------|-----------|
| Halaman Sampul | ✅ | "SKRIPSI" |
| Halaman Pengesahan | ✅ | Muncul di Daftar Isi |
| Halaman Pernyataan | ✅ | Muncul di Daftar Isi |
| Motto | ✅ | Muncul di Daftar Isi |
| Persembahan | ✅ | Muncul di Daftar Isi |
| Prakata | ✅ | Muncul di Daftar Isi |
| Daftar Isi | ✅ | |
| Daftar Tabel | ✅ | |
| Daftar Gambar | ✅ | |
| Daftar Simbol | ✅ | Via `\lambang` |
| Intisari | ✅ | Bahasa Indonesia |
| Abstract | ✅ | Bahasa Inggris |

### Bagian Utama (Studi Empiris)
| Bab | Judul | Isi |
|-----|-------|-----|
| **Bab 1** | Pendahuluan | Latar Belakang, **Rumusan Masalah**, Batasan Masalah, Tujuan Penelitian, Manfaat Penelitian, Sistematika Penulisan |
| **Bab 2** | Tinjauan Pustaka | Studi empiris terkait configuration drift, terminologi dasar, manajemen konfigurasi infrastruktur, paradigma deployment alternatif, evaluasi GitOps/ArgoCD, research gap |
| **Bab 3** | Metode Penelitian | Evaluasi empiris terkontrol, variabel & intervensi, 7 skenario penyimpangan, protokol pengukuran, analisis statistik komparatif (Mann–Whitney U, Cohen's d), ancaman validitas, lingkungan eksperimen |
| **Bab 4** | Hasil dan Analisis | Hasil E1–E3 (R1 konsistensi, R2 waktu deteksi/pemulihan/identifikasi akar masalah, R3 traceability), statistik deskriptif, uji perbandingan, ukuran efek, interpretasi, pembahasan |
| **Bab 5** | Kesimpulan dan Saran | Kesimpulan per dimensi evaluasi, saran, keterbatasan |

### Bagian Akhir
| Elemen | Ada? |
|--------|------|
| Daftar Pustaka | ✅ |
| Lampiran | ✅ | Kode, konfigurasi, data primer |

---

## Perbedaan Kunci: Proposal vs Skripsi

| Aspek | Proposal | Skripsi |
|-------|----------|---------|
| Class option | `[proposal]` | `[skripsi]` |
| Cover text | "PROPOSAL TUGAS AKHIR" | "SKRIPSI" |
| Bab 1 | Pendahuluan (Rumusan Masalah) | Pendahuluan (Rumusan Masalah) |
| Bab 2 | Penelitian Terkait | Tinjauan Pustaka |
| Bab 3 | Metode dan Rancangan | Metode Penelitian |
| Bab 4 | Jadwal Penelitian | Hasil dan Analisis |
| Bab 5 | ❌ Tidak ada | Kesimpulan dan Saran |
| Preliminary pages | Minimal | Lengkap |
| Lampiran | ❌ Tidak ada | ✅ Ada |

---

## Panduan Penulisan Bahasa

- Gunakan **bahasa Indonesia** (`[indonesia]`)
- Bahasa Inggris hanya untuk: judul, abstract, istilah teknis
- Istilah teknis boleh dalam bahasa Inggris dengan penjelasan Indonesia pada pertama kali disebut
- Gunakan Glosarium untuk jargon yang membingungkan

---

## Panduan Diagram dan Flowchart

- **Bagan Alir Metodologi** (Bab 3 Proposal / Bab 3-4 Skripsi): Wajib ada, visualisasi tahapan
- **Arsitektur Sistem** (Bab 3-4): Diagram komponen dan hubungannya
- **ERD / Skema Database** (jika relevan): Diagram relasi entitas
- **UI/UX Wireframe atau Mockup** (jika ada antarmuka): Rancangan tampilan
- **Gantt Chart** (Bab 4 Proposal): Jadwal penelitian berbasis bulan
- Semua diagram menggunakan environment `figure` dengan caption dan label

---

## Referensi Cepat LaTeX

### Citasi
```latex
\citep{key}   % (Author, Year)
\citet{key}   % Author (Year)
```

### Gambar
```latex
\begin{figure}[H]
  \centering
  \includegraphics[width=0.8\textwidth]{figures/nama-file}
  \caption{Deskripsi gambar}
  \label{fig:label}
\end{figure}
```

### Tabel
```latex
\begin{table}[H]
  \centering
  \caption{Judul tabel}
  \begin{tabular}{|l|c|r|}
    \hline
    Kolom 1 & Kolom 2 & Kolom 3 \\
    \hline
    Data & Data & Data \\
    \hline
  \end{tabular}
  \label{tab:label}
\end{table}
```

### Kode / Listing
```latex
\begin{lstlisting}[language=yaml, caption={Judul}]
# kode di sini
\end{lstlisting}
```

---

## Kompilasi

```bash
export PATH="/Library/TeX/texbin:$PATH"
cd proposal/  # atau cd skripsi/
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```

---

## Catatan Penting

- Jangan lupa mengisi metadata (nama, NIM, dosen pembimbing, dosen penguji) di `main.tex`
- Ganti `figures/logougm.pdf` dengan logo UGM resmi
- Untuk proposal: fokus pada **perencanaan**, bukan hasil
- Untuk skripsi: setiap bab harus terstruktur dan merujuk ke pedoman
- Gunakan `\bibliography{references}` untuk daftar pustaka
- Pastikan semua `\citep` / `\citet` ada di `references.bib`
