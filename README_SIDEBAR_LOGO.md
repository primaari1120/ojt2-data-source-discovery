# Sidebar Logo Update

Pembaruan untuk UI versi Compact Layout & Sidebar Fix. Ganti ikon sidebar dengan logo PNG lokal di atas latar kotak putih 56 x 56 px, sudut membulat 12 px. Tulisan di sebelahnya tepat dua baris:

Smart Data
Source Discovery

## Instalasi

1. Simpan gambar logo dari chat ke komputer sebagai PNG.
2. Hentikan Streamlit (Ctrl+C) dan backup file UI lama.
3. Salin `15_adaptive_workflow_streamlit.py` dari ZIP ke folder aplikasi.
4. Buat folder `assets` di sebelah file UI dan simpan logo dengan nama **`sds_logo.png`** di dalamnya:

```text
Demo Tools/
  15_adaptive_workflow_streamlit.py
  assets/
    sds_logo.png
```

File gambar asli belum tercakup di ZIP: gambar chat tidak tersedia sebagai file yang dapat diakses saat ekspor. Gunakan logo milik pengguna dari chat; tidak ada logo pengganti atau hasil gambar ulang yang dimasukkan.

5. Jalankan kembali:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\15_adaptive_workflow_streamlit.py
```

Lakukan Ctrl+F5 jika browser masih menampilkan tampilan lama. Pastikan nama file benar, bukan `sds_logo.png.png`. Logo dimuat dari disk dan disisipkan sebagai data PNG lokal, tanpa mengambil gambar dari internet. Jika PNG belum ada atau tidak terbaca, aplikasi tetap berjalan dengan nama aplikasi.

## Batas perubahan dan verifikasi

Hanya CSS brand dan fungsi sidebar yang berubah. Konten enam halaman, layout compact, perilaku collapse yang sudah diperbaiki, field matching, ranking, cache, History, serta seluruh kode di luar dua fungsi tersebut identik secara AST dengan versi sebelumnya. Tidak perlu mengganti modul engine, SQLite, kamus, model, venv, atau konfigurasi.

Verifikasi browser dilakukan dengan PNG fixture terpisah, bukan logo asli pengguna: gambar dapat dimuat, kotak putih 56 x 56 dengan radius 12 px, judul dua baris sesuai permintaan, collapse/reopen berfungsi, dan gambar yang belum ada tidak menimbulkan exception. Logo asli akan tampil setelah pengguna menyimpan PNG pada lokasi di atas.
