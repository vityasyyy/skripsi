# Skripsi: Perbandingan Terkontrol Paradigma Deployment Manual dan GitOps dalam Menghadapi Penyimpangan Konfigurasi pada Klaster Kubernetes

> Studi Kasus InvenioRDM | Departemen Ilmu Komputer dan Elektronika, FMIPA UGM

Repository ini berisi source LaTeX untuk **Proposal Tugas Akhir** dan **Skripsi** penelitian tentang perbandingan terkontrol paradigma deployment manual dan GitOps dalam menghadapi penyimpangan konfigurasi pada klaster Kubernetes, dengan studi kasus InvenioRDM. Baseline manual direpresentasikan oleh prosedur imperatif terotomasi berbasis kubectl; waktu reaksi manusia tidak diukur.

> **Status metode:** Kedua mode dijalankan berurutan pada satu stack InvenioRDM produksi-like; HPA normal aktif pada kedua mode dan skenario A adalah kontrol HPA, terpisah dari efikasi ArgoCD. Harness live dan protokol kolektor ada di [`experiments/live/README.md`](experiments/live/README.md) dan [`experiments/LIVE-OBSERVER.md`](experiments/LIVE-OBSERVER.md).

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
make presentation      # Kompilasi deck proposal
make presentation-skripsi # Kompilasi deck sidang skripsi
make all               # Kompilasi proposal, skripsi, dan kedua deck
make clean             # Bersihkan file build

# Docker (tidak perlu texlive)
make proposal-docker
make skripsi-docker
make presentation-docker
make presentation-skripsi-docker
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
├── presentation/
│   ├── proposal/                    # Deck proposal
│   └── skripsi/                     # Deck sidang skripsi
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

Setiap push ke `main`/`master` yang mengubah berkas LaTeX, `Makefile`, atau workflow akan memicu GitHub Actions untuk mengompilasi proposal, skripsi, deck proposal, dan deck sidang skripsi. Empat PDF tersedia sebagai artifact di halaman Actions. Pada push, workflow juga membuat rilis GitHub bernama **Tugas Akhir** dengan aset `proposal.pdf`, `skripsi.pdf`, `proposal-presentation.pdf`, dan `skripsi-presentation.pdf`.

---

## Topik Penelitian

## Deck Sidang

`presentation/skripsi/main.pdf` adalah deck sidang skripsi 22 halaman. Build lokal: `make presentation-skripsi`; build Docker: `make presentation-skripsi-docker`.

## Release

Push ke `main` yang menyentuh konten tugas akhir menjalankan empat kompilasi dan membuat release **Tugas Akhir** dengan aset `proposal.pdf`, `skripsi.pdf`, `proposal-presentation.pdf`, dan `skripsi-presentation.pdf`.
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
