# OJT 2 — UI Theme Update

Tema Streamlit disesuaikan dengan SMART_DATA_SOURCE_DISCOVERY_INTERACTIVE_MOCKUP_V1.html: latar biru pucat, judul navy, sidebar dengan brand bergradasi, kartu putih, garis lembut, tombol biru, dan tab berbentuk pill.

## Isi dan batas perubahan

Hanya `15_adaptive_workflow_streamlit.py` yang perlu diganti. Perubahan kode terbatas pada CSS di fungsi `inject_style()`. Seluruh fungsi lain identik secara AST dengan versi terakhir sebelum perubahan tema. Enam menu, teks, tabel, input, callback, dashboard, field matching, ranking, cache, serta perbaikan Mapping History tetap dipertahankan.

Konten dummy dan fitur tambahan dari mockup HTML tidak dimasukkan. Kontrol tetap menggunakan Streamlit; ini penerapan tema, bukan konversi aplikasi menjadi HTML statis.

## Pemasangan di Windows / PowerShell

1. Hentikan aplikasi dengan Ctrl+C di terminal Streamlit.
2. Backup file UI lama ke folder backup terpisah.
3. Ekstrak ZIP, lalu salin hanya `15_adaptive_workflow_streamlit.py` ke folder aplikasi yang sama dengan modul engine.
4. Jalankan lagi dari folder aplikasi:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\15_adaptive_workflow_streamlit.py
```

Gunakan venv dan dependency yang sudah dipakai aplikasi. Pembaruan ini tidak membutuhkan instalasi package, migrasi database, atau pengunduhan model baru. Jika browser masih menampilkan tema lama, lakukan hard refresh (Ctrl+F5).

Tidak perlu mengganti `ojt2_discovery_core.py`, modul engine, file SQLite, kamus bilingual, model, atau konfigurasi. Khususnya, pertahankan perbaikan lifecycle koneksi SQLite yang sudah diterapkan. Untuk rollback, hentikan Streamlit dan kembalikan backup file UI.

## Validasi

Diuji pada Streamlit 1.67 dengan fixture katalog dan histori sintetis terpisah dari data pengguna:

- Python syntax dan pemeriksaan UI statis: lulus.
- Perbandingan AST: hanya fungsi `inject_style()` berubah; semua kode lain identik.
- Browser Chromium, enam halaman: tanpa exception; teks halaman, nilai/label input, daftar tombol, dan jumlah dataframe identik sebelum/sesudah styling.
- Layout lebar 390 px: tanpa overflow horizontal pada halaman utama; sidebar native dapat ditutup.
- Regression Mapping History: dua record dengan nama objek sama, pemilihan ID, pergantian catatan, dan kondisi histori kosong lulus; hash database pengujian tidak berubah.

Jika validator sebelumnya tersedia di folder aplikasi, pemeriksaan statis dapat dijalankan dengan:

```powershell
.\.venv\Scripts\python.exe .\25_validate_clean_ui.py
```

Pengujian ini menggunakan data sintetis; verifikasi terakhir di lingkungan pengguna tetap melalui aplikasi dengan katalog lokalnya. Paket tidak memuat database, credential, histori PIC, data produksi, venv, atau model embedding.
