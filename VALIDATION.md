# Validasi kode eksperimen YAFS

Pemeriksaan terakhir: 30 September 2026. Dokumen ini menggantikan versi 10 September 2026
(topologi Barabasi-Albert, workload acak, 66 simulasi), yang tidak lagi berlaku untuk kode ini.

## Pemeriksaan yang lulus

- **25 pengujian otomatis** (`python -B -m unittest discover -s tests`): 16 pengujian protokol
  YAFS dengan fixture kecil buatan sendiri (bukan topologi hierarkis), dan 9 pengujian model
  workload (koefisien cloud peka CPU, deadline terkopel vs tetap, `cpu_rate`, seed kamera
  runner yang membuat deadline tetap antarlevel). Cakupan protokol:
  - adapter bandwidth tidak mengubah konfigurasi kanonis; double conversion ditolak,
  - latensi optimizer cocok dengan trace YAFS untuk satu link dan multihop tanpa antrean,
  - reservasi CPU instructions/deadline tetap berlaku bila `cpu_rate` tidak ada; tidak ada
    shared CPU scheduler baru,
  - request lokal yang belum selesai masuk denominator; deadline pending dan missed dibedakan,
  - drain window dan kasus tanpa emisi,
  - seed source reproducible dan berbeda antar-source/run,
  - budget, riwayat best-fitness, pairing run yang hilang, effect size, koreksi Holm.
- **Integritas YAFS:** `python -B -m runner.integrity` melaporkan 12 file `yafs/` tidak berubah
  (SHA-256 terhadap `SOURCE_MANIFEST.json`). Pemeriksaan yang sama dijalankan sebelum dan
  sesudah setiap eksperimen oleh `runner.run_experiment`.
- **Kualitas kode:** `pyflakes` bersih pada `placements`, `runner`, `analysis`, `generator`,
  `config`, dan `tests` (`yafs/` sengaja tidak disentuh).

## Topologi hierarkis

Diuji dengan manifest sintetis `data/cameras_SYNTHETIC.csv` (46 kamera, 16 persimpangan, 4 zona):

- Hasil: L1 = 16, L2 = 4, L3 = 1, cloud = 1 (22 node); 41 link (16 L1-L2, 20 east-west,
  4 L2-L3, 1 L3-cloud). Graf terhubung.
- `Topology.load` YAFS asli memuat 22 node dan 41 edge.
- Konversi BW ke engine memakai `config.units.engine_topology` (BW kanonis bytes/ms dibagi 1e6):
  1 Gbps menjadi 0,125 dan 500 Mbps menjadi 0,0625.

## Integrasi (simulasi YAFS)

| Batch | Konfigurasi | Simulasi |
| --- | --- | --- |
| Smoke A | `app-layering` (4 level), 1 run, Greedy/Random/GA, budget 40, emisi 2000 ms, drain 2000 ms | 12 |
| Smoke B | `app-layering` (4 level), 1 run, 8 algoritma, budget 30, emisi 1000 ms, drain 1000 ms | 32 |
| Smoke C | `fps-intensity` (7 level), 1 run, Greedy/Random/GA, budget 60, emisi 2000 ms, drain 2000 ms | 21 |
| Smoke D | `fps-fixed-deadline` (7 level), konfigurasi sama dengan Smoke C | 21 |
| Smoke E | `fps-fixed-deadline` (7 level), 1 run, Greedy/Nearest/MinLatency/GA/Random, budget 60, emisi 2000 ms, drain 2000 ms | 35 |

Total 121 simulasi selesai tanpa error, dan `analysis.constraint_analysis` berhasil dijalankan
pada kelima batch. Yang diperiksa:

- Emisi masuk akal terhadap perhitungan kasar (46 kamera x ~10 fps x 2 s x jumlah lapisan):
  emitted 905, 1852, 2748, 3616 untuk 1-4 lapisan pada Smoke A.
- Seluruh source berada di node bertipe L1 (184 source pada 4 lapisan).
- Runner menghentikan eksekusi bila emisi menyimpang dari jadwal; tidak terjadi.
- Pada level 1-2 emitted sama dengan completed untuk semua algoritma. Pada level 3-4 Smoke A,
  Random menyisakan request yang belum selesai (2748 emitted / 2691 completed dan 3616 / 3590).
  Level 3-4 Smoke B tidak saya tinjau satu per satu.

Ini uji operasional, bukan benchmark publikasi atau bukti peringkat algoritma.

## Estimasi optimizer vs trace YAFS pada topologi hierarkis

Skenario beban sangat rendah (fps x 0,05), manifest sintetis. Latensi estimasi optimizer
(`_calc_times`) dibandingkan dengan latensi trace (waktu selesai aktuator - waktu emisi):

| Kasus | Request | Hasil |
| --- | --- | --- |
| 1 lapisan, Random | 184 | 70 request tanpa tumpang tindih: selisih maksimum 0,000000 ms. 32 request menyimpang (sampai ~12 ms), seluruhnya tumpang tindih dengan request lain. Tidak ada yang lebih cepat dari estimasi. |
| 4 lapisan, GA | 736 | 566 request lebih lambat dari estimasi (sampai ~66 ms), tidak ada yang lebih cepat. Tidak ada request bebas tumpang tindih, karena empat modul satu kamera mulai serentak. |

Penyimpangan terlokalisasi pada antrean link native YAFS: antrean CPU modul nol, sedangkan
2730 dari 3128 baris link memiliki `buffer > 0`. Estimasi optimizer tidak memodelkan antrean
link, sehingga ia adalah batas bawah tanpa antrean. Skrip pembanding tidak ada di repositori.

## Yang belum divalidasi

- **Manifest CityFlowV2 belum diekstrak.** Seluruh hasil di atas memakai manifest sintetis.
- **Parameter placeholder** wajib diganti sebelum hasil dipakai di paper: speedup L1b/L2/L3/cloud,
  `t_ref_ms` dan RAM modul, `FRAME_BYTES` (perkiraan), rentang fps, BW L3-cloud, PR L2-L3.
- **Desain fps hanya diuji singkat** (Smoke C dan D: 1 run, 3 algoritma). Hasilnya operasional
  saja: ketuntasan on-time turun pada kedua desain saat fps naik (mis. GA x6: 0,16 pada deadline
  1000/fps dan 0,22 pada deadline tetap; deadline kamera tetap 116,185 ms pada semua level
  desain deadline tetap), sehingga penurunan terutama berasal dari beban,
  bukan dari pengetatan deadline. Bukan bukti peringkat algoritma.
- **Baseline Nearest dan MinLatency** (hop terdekat / estimasi latensi terendah yang muat) lolos uji
  admisi RAM/CPU dan tidak lebih jauh/lambat dari Greedy pada skenario uji. Pada Smoke E
  (budget metaheuristik hanya 60), keduanya mengungguli Greedy, dan pada fps x2-x3 juga GA dan
  Random (mis. x2: on-time 1,000 pada keduanya vs 0,550 GA, 0,468 Random, 0,254 Greedy).
  Ini menunjukkan heuristik sederhana yang sadar sumber adalah pembanding yang kuat; belum ada
  kesimpulan peringkat karena 1 run, budget kecil, dan manifest sintetis.
- **`time_log.json` kini mencatat `cloud_pressure`** (koefisien aktual, tekanan RAM/CPU fog, layanan di
  cloud) untuk placement final; diverifikasi pada smoke run (mis. fps x6, Greedy: koefisien 0,0150,
  tekanan CPU 0,974, 100 dari 184 layanan di cloud).
- **Penalti cloud adaptif kini memakai tekanan `max(RAM, CPU)` dari layanan yang ditempatkan di fog.**
  Angka 0,0947 (fps x1) dan 0,0150 (fps x6) di skenario 4 lapisan dihitung dari total demand
  seluruh layanan (versi RAM-saja tetap 0,1371); koefisien aktual pada placement hasil optimasi
  berbeda (GA, budget 60, x6: 0,0218 dengan reservasi CPU fog 39.308 / 46.000 inst/ms) dan
  harus dilaporkan sebagai tekanan reservasi fog berdasarkan placement. Manfaatnya belum dibuktikan; ablasi `--cloud-mode` (adaptive/constant/none) belum dijalankan.
- **Benchmark penuh** (30 run per level, budget 3000) belum dijalankan.
- **Tidak diperiksa ulang pada kode ini:** invarian emitted = completed + unfinished,
  on-time + miss + pending = emisi, ledger emisi identik antarstrategi, dan reprodusibilitas
  seed generator baru. Invarian tersebut diperiksa pada pipeline sebelumnya.
- Waktu emisi periodik dibulatkan ke ms terdekat; efeknya belum diukur.
- Seluruh modul satu kamera menerima frame pada fase yang sama; realisme asumsi ini dan
  pengaruhnya pada antrean link belum dievaluasi.
- Skema seed runner masih berbasis hash (`stable_seed`), bukan rumus seed yang direncanakan.

## Batas model YAFS

YAFS tidak membagi CPU antar-modul di node yang sama: tiap modul memiliki antrean FIFO sendiri
dan memakai IPT penuh. Kapasitas node hanya ditegakkan oleh placement (reservasi `cpu_rate`).
Model aplikasi adalah BOT; aliran DET -> REID sebagai pipeline belum dipakai. Energi tetap
proxy per-task, bukan pengukuran energi perangkat.
