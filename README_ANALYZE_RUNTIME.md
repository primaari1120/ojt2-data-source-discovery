# Analyze Runtime & History Update

Setiap proses Analyze menampilkan durasi dalam detik pada Discovery Results. Saat PIC memilih Save PIC Review to History, durasi dan waktu mulai/selesai UTC ikut disimpan bersama review. History menambahkan kolom Analyze time (s) dan detail waktu pada record terpilih.

## Perilaku waktu

- Timer menggunakan `time.perf_counter()` yang monotonic, bukan selisih jam sistem.
- Cakupan: perencanaan pencarian, discovery/ranking, dan supporting source untuk kandidat yang pertama kali ditampilkan. Cache supporting source yang masih valid tetap dipakai, sehingga Analyze berulang tidak memaksa penghitungan ulang yang tidak diperlukan.
- Tidak menghitung pembacaan/upload dokumen sebelum Analyze, pemuatan awal aplikasi/katalog, rendering browser, waktu menunggu keputusan PIC, atau pencarian supporting source tambahan saat pengguna membuka kandidat lain.
- Durasi selesai dibekukan. Pindah tab/kandidat, menunggu review, dan membuka History tidak menambah durasi tersebut.
- Analyze berikutnya mendapat Run ID baru. Penghitungan ulang setelah alias feedback, koreksi manual, atau feedback dari Metadata Explorer juga mendapatkan runtime baru yang melekat pada hasil baru.
- Analyze valid dengan nol kandidat tetap menampilkan durasi; belum ada kandidat untuk disimpan sebagai PIC review. Input yang belum cukup tidak dianggap Analyze selesai. Kegagalan tidak memakai ulang durasi/results dari run sebelumnya.
- Durasi terikat pada requirement, scope database, dan revisi katalog. Durasi dengan konteks yang tidak cocok tidak dimasukkan ke record review.

## Penyimpanan dan kompatibilitas

Durasi disimpan sebagai angka detik beserta Run ID, status, waktu mulai/selesai UTC, pemicu, dan cakupan pengukuran di `score_json.analysis_runtime` pada tabel `mapping_history` yang sudah ada.

Tidak ada penambahan kolom/tabel SQLite, migrasi, reset, atau penggantian file database. Record lama tetap dapat dibuka: durasinya kosong pada tabel dan ditandai belum tercatat pada detail, bukan diisi angka nol. Angka mentah tetap disimpan; tampilan dibulatkan dua desimal.

Penyimpanan permanen tetap mengikuti alur Save PIC Review to History. Menekan Analyze saja menampilkan hasil dan waktunya pada sesi; tidak membuat review otomatis.

## File dan pemasangan

Paket berisi empat file Python:

- `15_adaptive_workflow_streamlit.py` — timer Analyze/reanalysis, hasil, dan kolom History.
- `ojt2_discovery_core.py` — menambahkan metadata runtime ke summary review, tanpa mengubah API atau schema. Perbaikan penutupan koneksi SQLite sebelumnya tetap dipertahankan.
- `ojt2_analysis_runtime.py` — modul baru, wajib berada di folder yang sama.
- `40_validate_analysis_runtime.py` — validator offline dan UI.

1. Hentikan Streamlit (Ctrl+C).
2. Backup file UI dan `ojt2_discovery_core.py` yang sedang dipakai.
3. Salin keempat file Python dari ZIP ke folder aplikasi. Jangan mengganti database, venv, model, kamus, assets/logo, atau konfigurasi.
4. Jalankan kembali:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\15_adaptive_workflow_streamlit.py
```

Tidak perlu package baru atau menjalankan ulang 07/09. Indikator Analyze memakai elapsed timer native Streamlit jika versi terpasang mendukungnya; pada versi lama indikator proses biasa tetap digunakan.

Definition tabel tetap berupa snapshot yang sudah dipilih pengguna. Pengembangan full DDL/SMO yang dibatalkan tidak diaktifkan kembali. Layout compact, logo/favicons, matching/ranking dan lineage dipertahankan.

## Pengujian

```powershell
.\.venv\Scripts\python.exe .\40_validate_analysis_runtime.py
.\.venv\Scripts\python.exe .\40_validate_analysis_runtime.py --ui
.\.venv\Scripts\python.exe .\37_validate_sqlite_lifecycle.py
```

Validator memakai database sementara, tidak membaca/mengubah histori pengguna atau SQL Server. Pengujian mencakup clock sistem yang berubah, durasi yang tetap setelah selesai, penolakan nilai invalid/konteks berbeda, record lama/baru, schema yang tidak berubah, batas pengukuran planning/discovery/support, penggunaan cache, serta kegagalan dan nol kandidat.

Verifikasi tambahan dengan fixture sintetis pada Streamlit 1.67:

- Alur Analyze -> ganti kandidat -> Save PIC Review -> History menyimpan durasi yang sama persis.
- Hasil ranking, skor dan evidence identik dengan pemanggilan engine langsung.
- Chromium menunjukkan durasi/UTC yang sama pada hasil dan History, tanpa exception atau overflow horizontal halaman; navigasi tidak menambah waktu.
- History lama dengan nama objek berulang, pergantian record, kondisi kosong, dan hash SQLite setelah pembacaan tetap lulus.
- Validator 25 (UI), 37 (lifecycle SQLite), dan 39 (snapshot definition) tetap lulus.

Paket hanya berisi source, validator dan README. Tidak ada database, histori PIC, credential, data produksi, venv, model, atau screenshot di dalamnya.
