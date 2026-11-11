# Object Definition Preview Update

Panel SQL Definition kini menampilkan definisi yang tersedia untuk semua jenis objek, termasuk struktur tabel fisik. Semua tampilan membaca snapshot metadata lokal; tidak membuka koneksi SQL Server atau menjalankan SQL/SP.

## Perilaku

- Jika `sql_definition` tersimpan, SQL asli ditampilkan tanpa diubah (View, SP, Function, atau DDL lain yang memang tersimpan).
- Table tanpa SQL module menampilkan preview `CREATE TABLE` yang direkonstruksi dari `catalog_columns`: urutan/nama kolom, tipe data, panjang, precision/scale, nullable, dan penanda IDENTITY.
- Preview tabel adalah **struktur kolom parsial**, bukan script DDL asli/lengkap. Default, computed expression, constraint, index, collation, serta seed/increment IDENTITY belum dicatat extractor saat ini. Nilai yang tidak tersedia ditandai; seed/increment tidak diasumsikan 1,1.
- Panjang `nvarchar`/`nchar` dari `sys.columns.max_length` dikonversi dari byte menjadi karakter. Varchar/varbinary MAX, decimal/numeric, serta fractional precision tipe waktu ditampilkan sesuai metadata yang tersimpan.
- View/Function tanpa module tetapi dengan metadata kolom menampilkan daftar struktur kolom. Tidak dibuatkan query SELECT atau logika pengganti.
- Jika module dan kolom sama-sama belum tersedia, panel menjelaskan keterbatasan snapshot. Izin/enkripsi tetap perlu diperiksa bila relevan; aplikasi tidak mengarang definisi.
- SP pembentuk/pengisi tabel tetap ditelusuri secara terpisah melalui lineage GENERATED_BY. Struktur tabel tidak diganti dengan kode SP pembentuk.

Dipakai konsisten oleh Metadata Explorer di UI utama, SQL Definition pada Source Detail/Lineage, supporting source, dan Explorer standalone script 11. Label ketersediaan Definition pada Explorer standalone kini menunjukkan Column structure bila struktur kolom tersedia.

## File paket

- `15_adaptive_workflow_streamlit.py` — UI utama diperbarui.
- `11_metadata_explorer_streamlit.py` — Explorer standalone dan label ketersediaan diperbarui; helper pencarian/lineage/pembaca katalog tetap sama.
- `ojt2_object_definition.py` — modul baru bersama untuk menyusun dan menampilkan definition.
- `39_validate_object_definition.py` — validator offline baru.

## Instalasi

1. Hentikan Streamlit (Ctrl+C).
2. Backup dua file UI bernomor 11 dan 15 yang sedang dipakai.
3. Salin keempat file Python di atas ke folder aplikasi yang sama. Modul baru harus berada di sebelah kedua file UI.
4. Pertahankan file SQLite, modul engine lain, folder assets/logo, kamus, model, venv, dan konfigurasi yang sudah ada.
5. Jalankan kembali:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\15_adaptive_workflow_streamlit.py
```

Tidak perlu instalasi dependency baru, migrasi SQLite, ataupun menjalankan ulang script 07/09 untuk pembaruan ini: metadata kolom yang dibutuhkan sudah disimpan extractor saat ini. Jika metadata suatu objek memang belum tercakup, tampilannya tetap mengikuti isi snapshot; lakukan refresh metadata melalui prosedur biasa bila diperlukan.

Layout compact, sidebar/logo, favicon, matching/ranking, cache, review, dan History yang sudah diperbaiki tetap dipertahankan.

## Pengujian

```powershell
.\.venv\Scripts\python.exe .\39_validate_object_definition.py
.\.venv\Scripts\python.exe .\25_validate_clean_ui.py
```

Validator baru hanya memakai fixture di memori; tidak membaca SQL Server atau SQLite. Mencakup 28 kasus tipe data, urutan dan escaping identifier, Unicode byte length, nullable, penanda IDENTITY tanpa seed palsu, enam tipe objek, module asli yang tidak berubah, metadata parsial/kosong, serta input snapshot yang tidak dimutasi.

Verifikasi tambahan di Cloud dengan fixture sintetis dan Streamlit 1.67: AppTest lulus pada Table/View/SP di Metadata Explorer, Source Detail dan supporting-table definition, serta Explorer standalone dan label Column structure. Chromium memverifikasi struktur tabel tampil, tipe `nvarchar(80)` dan `decimal(18,2)` benar, tanpa exception atau overflow horizontal halaman. Perbandingan AST memastikan kode di luar tampilan definition pada kedua file tetap identik.

Paket hanya berisi source/validator dan README; tidak memuat katalog, histori PIC, data produksi, credential, venv, model, atau PNG fixture pengujian.
