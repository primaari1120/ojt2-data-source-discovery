# Perbaikan Mapping History — UI saja

Penyebab KeyError: tabel display menggunakan key ID, tetapi dropdown membaca id pada baris display. Dropdown kini memakai id dari record repository asli dan label menyertakan ID agar record dengan waktu/kandidat sama dapat dibedakan.

Pemasangan: hentikan Streamlit, backup file UI, lalu replace hanya 15_adaptive_workflow_streamlit.py pada folder Demo Tools. Jalankan kembali Streamlit. File database, history, credential, model, engine matching, dan ojt2_discovery_core.py tidak perlu diganti atau direset.

Pengujian Cloud: error direproduksi sebelum patch; setelah patch diuji daftar dua record, pemilihan record dengan kandidat/waktu sama, perpindahan notes antar-record dan empty history. Tidak ada exception. Hash SQLite uji sebelum-sesudah identik. Static UI regression 25 juga PASS.
