# Beban uji dan artefak historis

Beban formal adalah **InvenioRDM nyata**, bukan NGINX. Sumber otoritatif dan
revisi referensi ada di [`../deployment-source.json`](../deployment-source.json).
Revisi itu adalah sumber yang diperiksa, **bukan bukti revisi yang sedang
diterapkan**. Sebelum eksperimen, rekam revisi aktual Application, hasil render,
digest hasil render, inventaris, image digest, dan penyesuaian isolasi yang ditinjau.
Jangan menyalin manifest Invenio menjadi sumber konfigurasi editable kedua di repo ini.

`s1/manifests.yaml` dan `s2/manifests.yaml` dipertahankan hanya sebagai artefak
surrogat historis. Keduanya tidak digunakan oleh instrumen aktif dan tidak boleh
menjadi workload formal, acuan reset Invenio, atau sampel untuk inferensi Invenio.
Hasil mock dan contoh CSV lama juga dipertahankan dengan makna historisnya.

Instrumen aktif, format bukti, batas keselamatan, serta pemeriksaan offline:
[`../README.md`](../README.md). Tidak ada perintah apply/deploy dalam alur aktif.
