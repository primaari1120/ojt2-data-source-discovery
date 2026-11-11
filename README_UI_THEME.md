# OJT 2 — Compact Layout & Sidebar Fix

Pembaruan ini menggantikan versi UI theme sebelumnya. Hanya file `15_adaptive_workflow_streamlit.py` yang perlu disalin ke folder aplikasi.

## Perubahan tampilan

- Sidebar dan brand mengisi lebar panel; margin berlebih dari scrollbar gutter dihilangkan. Menu aktif memakai lebar area navigasi dengan margin 10 px.
- Aturan lebar sidebar hanya berlaku saat panel terbuka. Ketika ditutup dengan panah, mekanisme native Streamlit melepas ruang sidebar dan konten melebar kembali. Tombol buka/tutup tetap tersedia.
- Upload Requirement memakai dua panel: dokumen dan review requirement.
- Discovery Results menempatkan daftar kandidat di samping ringkasan, strategi, interpretasi, dan pesan status. Source Detail, metrik, dan empat tab tetap tersedia di bawahnya.
- Metadata Explorer memakai filter dalam satu baris, lalu panel daftar dan detail berdampingan. Settings menempatkan konfigurasi/diagnostik di samping business vocabulary. History dan Recent Reviews memakai kartu yang konsisten.
- Jarak antarbagian, padding, tombol, dan heading lebih rapat mengikuti mockup HTML. Warning/info/error memakai teks 12 px dan tinggi mengikuti isi, tanpa memotong pesan.
- Panel berdampingan ditumpuk pada layar yang lebih kecil. Tabel lebar tetap dapat digeser secara horizontal di dalam tabel.

Seluruh teks, tabel, data, kontrol, dan fungsi tetap dipertahankan. Isi dummy HTML tidak ditambahkan. Perubahan hanya di penyajian UI: CSS dan penempatan elemen dalam container/columns. Field matching, ranking, akses SQL/SQLite, cache, dan perbaikan History sebelumnya tetap digunakan.

## Cara memasang

1. Hentikan Streamlit dengan Ctrl+C.
2. Backup `15_adaptive_workflow_streamlit.py` yang sedang dipakai.
3. Ekstrak ZIP ini dan replace hanya file Python tersebut di folder aplikasi.
4. Jalankan kembali dari folder aplikasi:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\15_adaptive_workflow_streamlit.py
```

Lakukan Ctrl+F5 jika browser masih menampilkan tampilan lama. Gunakan venv aplikasi yang sudah ada. Jangan mengganti modul engine, `ojt2_discovery_core.py` yang sudah diperbaiki, database SQLite, kamus, model, atau konfigurasi. Paket ini tidak memerlukan migrasi data dan tidak membawa database, credential, data produksi, histori PIC, venv, atau model embedding.

Untuk rollback, hentikan aplikasi dan kembalikan backup file UI.

## Hasil verifikasi

Diuji dengan Streamlit 1.67, Chromium, serta katalog dan histori sintetis terpisah dari data pengguna:

- Python syntax dan `25_validate_clean_ui.py`: lulus.
- Pemeriksaan AST: helper di luar presentasi identik; seluruh pemanggilan lama di luar layout serta string konten tetap sama.
- Enam halaman: teks/kontrol tetap tersedia dan tidak ada exception. Dataframe payload dan nilai widget identik sebelum/sesudah susunan panel diubah.
- Analyze dan pergantian kandidat: lulus.
- Sidebar mengisi lebar, dapat ditutup dan dibuka lagi, serta tidak menyisakan gutter pada lebar 1920, 1440, 1024, 900, dan 390 px.
- Skenario hasil kosong seperti screenshot pengguna: judul kembali ke kiri setelah collapse pada lebar 1440 dan 950 px.
- Keempat tab Field Mapping, Source Gap, Lineage, dan PIC Review: dapat dibuka; tombol simpan tetap memerlukan consent PIC.
- Warning dihitung browser pada ukuran 12 px; layout mobile tidak menyebabkan overflow horizontal halaman utama.
- Mapping History: pergantian dua record dengan nama objek sama, kondisi kosong, dan hash database pengujian tidak berubah.

Jika validator lama tersedia di folder aplikasi, pemeriksaan statis dapat dijalankan dengan:

```powershell
.\.venv\Scripts\python.exe .\25_validate_clean_ui.py
```

Tes menggunakan fixture sintetis; katalog perusahaan tetap dibaca dari konfigurasi aplikasi milik pengguna.
