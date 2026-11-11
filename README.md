[Download pembaruan v0.6](./OJT2_Generalized_Matching_Update_v06.zip?raw=true)

# v0.6 — Ranking dan performa Analyze

Paket ini mencakup pembaruan generalized matching sebelumnya beserta perbaikan ranking dan performa. Salin seluruh file pembaruan ke folder kode aplikasi lama; pertahankan lokasi katalog, SQLite history dan folder model. Tidak perlu reset DB atau menghapus feedback.

Jalankan: python 36_validate_ranking_performance.py
Jalankan: python 34_validate_generalized_matching.py
Uji model lokal: python 35_validate_bilingual_model.py --report model_report.json
Mulai aplikasi: python -m streamlit run 15_adaptive_workflow_streamlit.py

## Perubahan

- Untuk request yang memiliki fields, ranking memakai evidence per field (maksimum 80 poin) dan konteks (maksimum 20). Bobot merupakan heuristik ranking, bukan confidence terkalibrasi atau verified coverage.
- Setiap requested field dihitung sekali. Hipotesis semantic tidak mendapat bonus berulang sebagai field tambahan. Hipotesis semantic, grain dan identifier diberi kekuatan lebih rendah daripada exact/alias yang jelas.
- Konflik jenis atribut mencakup nama vs tipe/klasifikasi dan klasifikasi vs organisasi; bukan pengecualian untuk pasangan field tertentu.
- Normalisasi/tokenisasi menggunakan cache yang menyertakan versi isi term rules sebagai key; perubahan operator glossary tidak memakai hasil lama.
- Embedding untuk scope metadata berizin dipersiapkan dalam batch; cache tetap terbatas. CPU default maksimum 4 thread untuk menghindari overhead thread berlebihan. OJT2_SEMANTIC_THREADS dapat diatur ke integer positif untuk menyesuaikan perangkat; OMP_NUM_THREADS yang eksplisit juga dihormati.
- Source Gap pada Results di-cache per sesi. Key meliputi request, kandidat, mapping, scope, catalog run, engine/rule version dan revisi repository history; perubahan feedback/config atau metadata menginvalidasi cache.
- Ranking evidence disimpan dalam candidate; tidak mengubah keputusan historis atau memberi approval otomatis.

## Reproduksi kasus pengguna

Purpose: Monitoring Data GDL. Source hint: GDL. Sepuluh field dari screenshot direproduksi pada fixture metadata demo yang sudah ada.

Versi lama: vwGDLListOutbound 65.3, vwGDLTrace 62.7.
Versi baru: vwGDLTrace 65.6, vwGDLListOutbound 42.8.
Tidak ada nama sumber GDL yang ditambahkan sebagai aturan ranking.

Waktu pada Cloud, 14 objek/10 field: cold Analyze 10.61 -> 9.54 detik; warm Analyze 2.50 -> 1.26 detik; first gap 1.33 -> 0.36 detik. Waktu ini bergantung pada hardware, ukuran katalog, cache, model dan thread; bukan janji bahwa Analyze satu menit di laptop akan menjadi satu detik. Pemanggilan pertama tetap memuat model.

## Validasi

16 skrip regresi lolos (termasuk validator 36). Model lokal sungguhan: hit@3 15/15, penolakan pasangan negatif 7/7. UI AppTest: mapping/ambiguity berfungsi, rerun kedua tidak menghitung ulang Source Gap. Tidak mengakses SQL Server pengguna.

Tidak ada field missing tidak berarti seluruh mapping verified. ID GDL -> GDLDetailID tetap memerlukan validasi grain/header-detail. Aturan bisnis/field bersyarat tetap memerlukan PIC.

---

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
