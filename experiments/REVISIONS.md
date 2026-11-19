# Revisi beku dan provenance kode

Dokumen ini menjawab satu pertanyaan utama: **kode atau data revisi mana yang
menghasilkan angka di skripsi?** Dokumen ini mencatat tag beku, commit
pasca-koleksi, dan batas antara apparatus koleksi dengan kode analisis. Angka
hasil ada di
[`docs/reproducibility/formal-20261029-results.md`](../docs/reproducibility/formal-20261029-results.md);
inventaris data ada di [`DATA.md`](DATA.md).

## Ringkasan identitas

| Peran | Tag | Objek tag | Commit | Keterangan |
|---|---|---|---|---|
| Apparatus koleksi | `thesis-collection-20261029` | `066ad19f9d7ee7b564d6cc55ce823e180e8f05ce` | `3572f3c1c11d3abc8b63882c4348b1b803d4256f` | Kode yang menjalankan batch formal `formal-20261029` |
| Analisis primer | `thesis-analysis-20261030` | `51aecc8ba97a9b5614d699cba200f6e6e42cb57c` | `a1d43eaf0d349249f1eb0a8e880badebe4eb851d` | Revisi kode analisis yang dilaporkan di Bab IV |
| Analisis sensitivitas | `thesis-sensitivity-20261030` | `035916c60a672dd76d38fec8b974bd74354272aa` | `6cfc99ec63a71825e88b53a96704c8c792891bd9` | Berkas `experiments/sensitivity/` untuk C-r02 |
| HEAD saat klasifikasi awal | — | — | `b6a4e3eace970269bb0b0e2b3058f6a6a000d23a` | Bukan revisi koleksi; HEAD bergerak setelah integrasi 2026-11-19 |

Ketiga tag adalah annotated tag. Commit yang ditunjuk diverifikasi dengan:

```bash
git rev-parse 'thesis-collection-20261029^{commit}'
git rev-parse 'thesis-analysis-20261030^{commit}'
git rev-parse 'thesis-sensitivity-20261030^{commit}'
git rev-parse HEAD
```

## Input beku batch formal

| Butir | Nilai |
|---|---|
| Batch | `formal-20261029` |
| Mode | live, satu stack InvenioRDM, dua mode berurutan |
| Revisi GitOps | `81ddd259780e0e6aef333811a0126f86d70a094e` |
| SHA-256 render | `a5efd711d661438590a730291c41b70d1c668b2672d51a54f68c0ff68e311703` |
| Revisi skripsi/instrumen | `3572f3c1c11d3abc8b63882c4348b1b803d4256f` |
| Seed | `20261029` |
| Urutan mode | `gitops`, lalu `imperative` |
| Urutan skenario | `E, A, G, D, C, F, B` |
| Konvensi waktu | `completed-observation-v1` |
| Cooldown / retry | 60 detik / 1 retry baseline pra-injeksi |

Nilai-nilai ini juga tercatat di
`experiments/formal-20261029/formal-20261029.manifest.json`,
`experiments/formal-20261029/PROVENANCE.json`, dan
`experiments/analysis-formal-20261029/live_analysis.json` (`batch.*`).

## Commit pasca-koleksi yang diklasifikasikan (`3572f3c..b6a4e3e`)

Tabel ini sengaja dibatasi pada `b6a4e3e`, titik handoff 19 November 2026.
Setelah itu, branch integrasi 2026-11-19 menambahkan:

- `9ba0a97` — `refactor(experiments): make sensitivity defaults repo-relative`;
- `45a7fa6` — `refactor(experiments): split harness and analyzer behind stable facades`;
- commit dokumentasi/provenance, koreksi tesis/deck, dan refresh PDF.

Pemisahan modul diuji dengan 492 tes inti + 9 tes sensitivity, keluaran analisis
beku yang identik, dan dry-run 210 sel. Commit-commit tersebut tidak mengubah
apparatus koleksi; `HEAD` tetap bukan revisi koleksi.

Klasifikasi yang dipakai:

- **docs** — hanya dokumen, LaTeX, deck, atau handoff; tidak mengubah kode
  eksperimen.
- **refactor** — bentuk kode, tooling, atau tipe berubah; perilaku eksperimen
  diklaim dipertahankan dan diuji ulang.
- **behavior** — perilaku runtime atau keluaran analisis berubah.

| Commit | Tanggal | Subjek | Klasifikasi | Dampak pada `experiments/` |
|---|---|---|---|---|
| `a1d43ea` | 2026-10-30 | `fix(analysis): describe scenario F by its current definition` | behavior (teks keluaran) | Catatan F di `analyze_live.py`; statistik tidak berubah |
| `ab9df20` | 2026-10-30 | `docs(thesis): report the completed formal results in Bab IV` | docs | — |
| `4099fc7` | 2026-10-30 | `docs(thesis): draw bounded conclusions and set out future work` | docs | — |
| `0e68fb0` | 2026-10-30 | `docs(thesis): finish appendix, expand glossary and correct abstracts` | docs | — |
| `fb20d7e` | 2026-10-30 | `docs(thesis): synchronise Bab I-III with the completed collection` | docs | — |
| `fb3a89a` | 2026-10-30 | `docs(thesis): report verified file recovery from the backup artifact` | docs | — |
| `a01a6c8` | 2026-11-11 | `docs(thesis): reconcile experiment results and polish draft` | docs | — |
| `a15dac4` | 2026-11-15 | `docs(thesis): standalone narrative, diagrams, and defense deck` | docs | — |
| `fffda55` | 2026-11-15 | `fix(thesis): converge references and correct diagram claim` | docs | — |
| `6cfc99e` | 2026-11-15 | `docs(thesis): clarify evidence and replace HTML diagrams with Mermaid` | behavior (analisis baru) | Menambahkan `sensitivity/c_r02_sensitivity.py` dan tesnya; tidak mengubah keluaran primer |
| `b0c0f82` | 2026-11-17 | `chore: refactor experiment code and align CS terminology` | refactor | Format, anotasi tipe, ekstraksi fungsi, tooling, dan tes; klaim tanpa perubahan perilaku |
| `e020630` | 2026-11-19 | `docs(handoff): transfer experiment verification and repo cleanup` | docs | — |
| `90aa781` | 2026-11-19 | `docs(handoff): record merged handoff state` | docs | — |
| `b6a4e3e` | 2026-11-19 | `docs(handoff): stop pinning the moving main tip` | docs | — |

Total diff `3572f3c..b6a4e3e`: 106 berkas, 15.137 baris ditambah dan 4.849
baris dihapus; 32 berkas di antaranya berada di `experiments/`. Untuk nilai
terkini setelah integrasi, jalankan `git diff --shortstat 3572f3c..HEAD`; angka
itu bergerak dan bukan identitas freeze.

## Teorema provenance

> **Kode di `HEAD` bukan kode koleksi.** Batch formal dijalankan pada
> `3572f3c`; `HEAD` memuat perubahan analisis, berkas sensitivity, dan refactor
> yang masuk setelah data dikumpulkan. Menjalankan `HEAD` pada klaster tidak
> mereproduksi batch dan tidak boleh disebut replikasi.

Konsekuensi praktis:

1. **Untuk mengaudit angka**, pakai keluaran beku di
   `experiments/analysis-formal-20261029/` dan berkas mentah di
   `experiments/formal-20261029/`; jangan menjalankan ulang analisis lalu
   menganggap hasilnya identitas baru.
2. **Untuk mereproduksi analisis**, jalankan `analyze_live.py` dari `HEAD`
   dengan seed `20261029`; hasilnya identik dengan tujuh keluaran beku (lihat
   [`docs/reproducibility/verification-2026-11-19.md`](../docs/reproducibility/verification-2026-11-19.md)).
3. **Untuk mengulang koleksi live**, diperlukan batch baru, izin baru, dan
   pembekuan apparatus baru. Tidak ada run live baru yang disetujui oleh
   dokumen ini.
4. **Untuk membaca sensitivitas C-r02**, pakai berkas di
   `experiments/sensitivity/`; berkas itu ditambahkan pada `6cfc99e` dan tidak
   mengubah analisis primer.

## Verifikasi

```bash
git diff --stat 3572f3c1c11d3abc8b63882c4348b1b803d4256f..HEAD -- experiments
git log --oneline 3572f3c1c11d3abc8b63882c4348b1b803d4256f..HEAD
git cat-file -t thesis-collection-20261029   # tag
git rev-parse 'thesis-collection-20261029^{commit}'
```

Berkas ini tidak menggantikan checksum data; checksum dan prosedur verifikasi
ada di [`DATA.md`](DATA.md).
