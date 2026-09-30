# Validasi kode eksperimen YAFS

Pemeriksaan diselesaikan 10 September 2026.

## Pemeriksaan yang lulus

- **16 pengujian otomatis**, termasuk pengujian langsung pada native YAFS.
- Adapter bandwidth tidak mengubah konfigurasi kanonis; double conversion ditolak.
- Latency optimizer cocok dengan trace YAFS untuk satu link dan multihop tanpa antrean.
- Native link queue yang memasukkan propagation tetap dipertahankan.
- Native concurrency per module tetap dipertahankan; tidak ada shared CPU scheduler baru.
- CPU reservation tetap instructions/deadline, bukan diganti dengan arrival-rate demand.
- Request lokal yang belum selesai masuk denominator; deadline pending dan missed dibedakan.
- Drain window dan empty-emission case bekerja.
- Seed source reproducible dan berbeda antar-source/run.
- Budget, best-fitness history, reset pengaturan ablasi, pairing missing run,
  zero-difference effect size, dan Holm correction diperiksa.

## Integrasi

**66 simulasi YAFS berhasil**:

| Batch | Konfigurasi | Simulasi |
| --- | --- | --- |
| Smoke | 2 aplikasi, 8 fog nodes, 1 run, 8 strategi, budget 40 | 8 |
| Integration | 2 aplikasi, 8 fog nodes, 5 run, 8 strategi, budget 70 | 40 |
| Stress check | 25 dan 250 aplikasi, 100 fog nodes, 1 run, 8 strategi, budget 40 | 16 |
| Ablation smoke | SA dan Random; tanpa headroom, cloud constant, random initialization | 2 |

Seluruh keluaran diperiksa untuk:

- Emitted = completed + unfinished.
- On-time delivery + deadline miss + pending deadline = seluruh emission.
- Emission ledger identik antarstrategi dalam instance yang sama.
- Analisis ringkasan dan peak-tier statistik berhasil pada batch integration.
- Hash source eksperimen dalam manifest integration cocok dengan source final.

Uji beban besar memakai emission 1000 ms dan drain 2000 ms. Ini pengujian
operasional, bukan benchmark publikasi atau bukti peringkat algoritma.

## Integritas YAFS dan sumber

Seluruh **12 file YAFS** identik byte demi byte dengan snapshot awal dan dengan
folder sumber saat pemeriksaan akhir. Verifikasi dilakukan melalui SHA-256 dan
daftar file. Seluruh Python source berhasil diparse.

Saya tidak menulis perubahan ke `/Users/adhitya/constraint-aware`. Pemeriksaan akhir
menemukan **7 file non-YAFS di folder sumber berbeda dari snapshot saat penyalinan**.
Perubahan itu tidak ditimpa atau digabungkan otomatis ke salinan ini. Rinciannya
tersimpan dalam `SOURCE_CHANGES_SINCE_COPY.json`, sedangkan hash snapshot lengkap
tersedia pada `SOURCE_MANIFEST.json`.

## Yang belum divalidasi

Benchmark penuh 10 tier × 30 run dengan budget 3000 belum dijalankan. Konfigurasi
fisik, kecocokan asumsi simulator, sensitivitas horizon/topology/bobot, dan
kesimpulan ilmiah masih perlu dievaluasi dalam riset utama.

YAFS tetap memiliki model eksekusi per module serta antrean link aslinya. Validasi
ini tidak mengubahnya menjadi model shared aggregate CPU atau jaringan fisik baru.
Energi tetap dilaporkan sebagai proxy per-task, bukan pengukuran energi perangkat.
