# Browser Tab Logo Update

Ikon tab browser (favicon) memakai PNG yang sama dengan logo sidebar: `assets/sds_logo.png`.

## Instalasi

1. Hentikan Streamlit (Ctrl+C) dan backup file UI lama.
2. Replace hanya `15_adaptive_workflow_streamlit.py` dari paket ini.
3. Pertahankan logo yang sudah terpasang di `assets/sds_logo.png` dalam folder aplikasi. Tidak perlu menyalin ulang PNG yang sama.
4. Jalankan lagi:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\15_adaptive_workflow_streamlit.py
```

Lakukan Ctrl+F5. Jika browser masih menyimpan ikon lama, tutup tab aplikasi lalu buka kembali alamatnya.

Tidak ada PNG, database, histori, model, credential, venv, atau modul engine dalam paket. PNG pengguna yang sudah ada tetap digunakan.

## Perubahan dan pengecekan

Perubahan hanya pada `page_icon` dalam konfigurasi halaman: memakai path lokal PNG jika tersedia, dengan ikon kaca pembesar sebagai fallback jika file belum ada. Judul tab dan seluruh kode lain tetap sama; dibandingkan secara AST.

Diuji melalui Chromium dengan PNG fixture lokal dan katalog sintetis: favicon yang dikirim merupakan PNG valid, judul tab tetap Smart Data Source Discovery, dan aplikasi tetap terbuka tanpa exception ketika PNG tidak tersedia. Logo asli pengguna akan dibaca dari file yang sama dengan sidebar.
