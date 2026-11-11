# Patch field matching v0.6.1 — hanya perubahan yang diperlukan

Untuk aplikasi yang sudah memakai paket v0.6 ranking/performance.

## Isi
- ojt2_field_matching.py: guard jenis atribut dan keluarga event workflow. Tidak menambahkan pasangan field atau nama tabel khusus Memorandum.
- ojt2_adaptive_core.py: pencatatan engine_version 0.6.1 dan rule_version v9.
- 38_validate_field_facet_guards.py: validator baru, termasuk 13 field Memorandum, kontrol lintas domain, penolakan hipotesis model berskor tinggi yang kontradiktif, serta pemeriksaan bahwa transferred feedback tidak menghidupkan kembali kandidat yang ditolak.

## Pemasangan Windows
1. Hentikan Streamlit dengan Ctrl+C dan backup dua file aplikasi di atas.
2. Copy hanya dua file aplikasi tersebut ke folder Demo Tools, pilih Replace. Tambahkan validator 38.
3. Pertahankan semua file lain. ojt2_discovery_core.py tidak termasuk patch ini: pertahankan versi SQLite lifecycle yang sudah diperbaiki. Tidak ada reset SQLite/history, perubahan kamus/model, atau reinstall venv.
4. Jalankan menggunakan interpreter venv:

```powershell
.\.venv\Scripts\python.exe .\38_validate_field_facet_guards.py
.\.venv\Scripts\python.exe .\38_validate_field_facet_guards.py --real-model
.\.venv\Scripts\python.exe .\34_validate_generalized_matching.py
.\.venv\Scripts\python.exe -m streamlit run .\15_adaptive_workflow_streamlit.py
```

Opsi --real-model membutuhkan model lokal yang sudah diprovision pada aplikasi. Tidak ada download otomatis.

## Hasil uji
18 skrip regresi PASS. Validator 38 diuji dengan dan tanpa model lokal sungguhan: 5 kelompok tes PASS, termasuk 10 kontrol atribut/event lintas domain. Pada schema sintetik yang diberikan pengguna: 2 cocok nama, 9 saran potensial yang tetap perlu review, dan 2 missing (Feedback Date dan Resubmit Date). Approve Date -> ReviewedDate dan Request Date -> CreatedDate tetap membutuhkan validasi bisnis; LeadTime tetap membutuhkan verifikasi rumus. Bukan 11 mapping verified.

Tidak mengubah file atau record history lama; koneksi ke SQL Server pengguna tidak dilakukan. Data uji memakai asumsi tipe datetime untuk tanggal, int untuk LeadTime, nvarchar untuk kolom lain, objek bernama vwMemorandumHistory, dan tanpa history PIC.
