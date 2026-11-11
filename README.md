# OJT2 Generalized Matching Update

[Download OJT2_Generalized_Matching_Update.zip](./OJT2_Generalized_Matching_Update.zip?raw=true)

ZIP SHA256: `a9fde95f840e2c1abd80580339a40b79e82ca5136675c1072d4c42af7b05c50b`

# Pembaruan generalized field matching OJT 2

Melanjutkan baseline 34 file Python lampiran, bukan membangun ulang aplikasi.

## Pemasangan pada aplikasi yang sudah ada

1. Hentikan Streamlit dan backup kode saat ini.
2. Salin seluruh file pembaruan bersama ke folder aplikasi lama, termasuk modul baru dan ojt2_bilingual_lexicon.json.gz. Dependency aplikasi lama tetap diperlukan.
3. Pertahankan lokasi SQLite katalog, history dan model saat ini. Tidak memerlukan reset history, penghapusan DB, refresh SQL Server atau download ulang model.
4. Jalankan python 34_validate_generalized_matching.py kemudian python -m streamlit run 15_adaptive_workflow_streamlit.py.
5. Untuk model lokal yang sudah tersedia: python 35_validate_bilingual_model.py --report bilingual_local_report.json.

## Bahasa dan model

Kamus dibundel offline: 35.612 istilah Indonesia dengan 226.031 hubungan terjemahan ke English. Sumber Wordnet Bahasa (MIT), melalui OMW 1.4, disejajarkan dengan Princeton WordNet 3.0. Lisensi dan sitasi disertakan. Terjemahan merupakan saran, bukan kesetaraan bisnis universal.

Model lokal opsional: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2. Gunakan path model yang sama melalui OJT2_SEMANTIC_MODEL_PATH atau default lama. Runtime tidak mendownload model atau mengirim metadata keluar. Jika belum tersedia, provisioning menggunakan utility 28 aplikasi sesuai prosedur internal. Weights model tidak dibundel.

Lingkungan pengujian: Python 3.12, sentence-transformers 3.4.1, transformers 4.48.3, torch 2.6.0 CPU; model revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42. Dependency yang sudah kompatibel tidak perlu diinstal ulang.

## Perilaku

Tokenisasi, acronym, urutan kata, bilingual dictionary dan semantic retrieval dipakai melalui matcher bersama. Discovery dan Metadata Explorer memakai resolver yang sama. Evidence fusion menyimpan retrieval_methods dan evidence_by_method, termasuk sinyal/risiko model. Skor bukan probabilitas. Nama objek/kolom tetap berasal dari katalog.

MISSING dipertahankan bila tidak ada kandidat yang layak. Kandidat ambigu tetap memiliki alternatif dan zero coverage factor. Identifier, nomor, label, unit, event dan grain tetap dibedakan. Tidak ada auto-JOIN atau eksekusi SQL bisnis. Approval PIC lokal dan rejection dipertahankan; history baru mencatat versi kandidat, history lama tidak diubah.

Tidak ditambahkan pasangan requirement-ke-kolom untuk contoh pengguna. Aturan demo domain lama masih dipertahankan untuk kompatibilitas; generalized tests mencakup domain None dan subject baru.

OJT2_APP_DATA_DIR opsional mengubah lokasi repository aplikasi; default lama tetap berlaku. OJT2_CATALOG_PATH tetap mengatur katalog. Pertahankan lokasi lama untuk membaca data yang sama.

## Pengujian

15 skrip regresi PASS, termasuk 18 kelompok tes baru validator 34. Validator 35 dengan model sungguhan: hit@3 15/15, pasangan negatif 7/7, isolasi semantic dari kamus PASS dan single-field discovery PASS. UI Streamlit AppTest PASS untuk saran, ambiguity, PIC choices dan missing.

Benchmark kecil sintetik ini bukan klaim akurasi production atau kelengkapan semua istilah bilingual. Tidak ada koneksi SQL Server pengguna atau pengujian tujuh dokumen asli. Fixture Excel yang dibutuhkan validator 16 tidak termasuk dalam lampiran.

## Sumber kamus

https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/omw-1.4.zip
https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip

Metadata gzip menyimpan jumlah istilah/pasangan dan SHA256 sumber. Seluruh proses matching runtime offline.
