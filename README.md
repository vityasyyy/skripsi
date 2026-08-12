# Skripsi: Evaluasi GitOps menggunakan ArgoCD terhadap Configuration Drift pada Deployment Aplikasi Multi-Service di Klaster Kubernetes

> Studi Kasus InvenioRDM | Departemen Ilmu Komputer dan Elektronika, FMIPA UGM

Repository ini berisi source LaTeX untuk **Proposal Tugas Akhir** dan **Skripsi** penelitian tentang evaluasi GitOps (ArgoCD) dalam mengurangi *configuration drift* pada deployment multi-service di klaster Kubernetes, dengan studi kasus InvenioRDM.

> **Sumber kebenaran:** Proposal Tugas Akhir (`content/proposal/`) sudah diterima dan direview dosen pembimbing. Seluruh konten repo (termasuk struktur skripsi) harus selaras dengan proposal tersebut.

---

## Quick Start

### Prerequisites

**Opsi A: Kompilasi Lokal (membutuhkan texlive)**
- macOS: `brew install --cask mactex`
- Linux: `sudo apt-get install texlive-full`
- Windows: [MiKTeX](https://miktex.org/) atau [TeX Live](https://tug.org/texlive/)

**Opsi B: Docker (tanpa texlive)**
- [Docker Desktop](https://www.docker.com/products/docker-desktop)

### Kompilasi

```bash
# Lokal
make proposal          # Kompilasi proposal
make skripsi           # Kompilasi skripsi
make all               # Kompilasi keduanya
make clean             # Bersihkan file build

# Docker (tidak perlu texlive)
make proposal-docker
make skripsi-docker
make all-docker
```

### Manual (tanpa Makefile)

```bash
cd content/proposal  # atau content/skripsi
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```

---

## Repository Structure

```
skripsi/
├── content/
│   ├── proposal/
│   │   ├── main.tex               # Metadata & struktur proposal
│   │   ├── ugmskripsi.cls          # LaTeX class file UGM
│   │   ├── chapters/               # BAB 1-4
│   │   │   ├── bab1-pendahuluan.tex
│   │   │   ├── bab2-penelitian-terkait.tex
│   │   │   ├── bab3-metodologi.tex
│   │   │   └── bab4-jadwal-penelitian.tex
│   │   ├── figures/
│   │   └── references.bib
│   │
│   └── skripsi/
│       ├── main.tex                # Metadata & struktur skripsi
│       ├── ugmskripsi.cls
│       ├── chapters/                # BAB 1-5 (Studi Empiris)
│       │   ├── bab1-pendahuluan.tex
│       │   ├── bab2-tinjauan-pustaka.tex
│       │   ├── bab3-metodologi.tex
│       │   ├── bab4-hasil-analisis.tex
│       │   └── bab5-kesimpulan-saran.tex
│       ├── figures/
│       ├── diagrams/                # Diagram TikZ dari proposal
│       ├── lampiran/
│       └── references.bib
│
├── docker/
│   └── Dockerfile                  # LaTeX build image
├── .github/
│   └── workflows/
│       └── compile-latex.yml      # CI: auto-compile on push
├── Makefile                        # Build automation
├── ugmskripsi.cls                  # Root copy of class file
└── .gitignore
```

---

## CI/CD

Setiap push ke `main`/`master` yang mengubah file `.tex`, `.bib`, atau `.cls` akan memicu GitHub Actions untuk mengompilasi proposal dan skripsi secara otomatis. PDF hasil kompilasi tersedia sebagai artifact yang bisa diunduh dari halaman Actions.

---

## Topik Penelitian

- **Judul:** Evaluasi GitOps menggunakan ArgoCD terhadap Configuration Drift pada Deployment Aplikasi Multi-Service di Klaster Kubernetes: Studi Kasus InvenioRDM
- **Pendekatan:** Studi empiris terkontrol (*quasi-experiment*) dengan dua lingkungan paralel
- **Metrik:** R1 konsistensi deployment, R2 waktu deteksi & pemulihan drift, R3 traceability (audit trail)
- **Teknologi:** Kubernetes, ArgoCD, InvenioRDM, Helm, kubectl

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| `logougm` not found | Ganti `content/*/figures/logougm.pdf` dengan logo UGM resmi |
| References `[?]` | Jalankan `bibtex main` lalu `pdflatex main.tex` 2x |
| `natbib` error | Pastikan texlive-full terinstall |
| PDF tidak update | `make clean` lalu kompilasi ulang |
| Docker error | Pastikan Docker Desktop berjalan |

---

Mahasiswa: **Muhammad Argya Vityasy** (23/522547/PA/22475)
Pembimbing: **Guntur Budi Herwanto, S.Kom., M.Cs.**
Program Studi Ilmu Komputer, FMIPA UGM