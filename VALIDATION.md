# Validasi kode eksperimen YAFS

Pemeriksaan terakhir: 1 Oktober 2026. Menggantikan versi 10 September 2026 (topologi
Barabasi-Albert, workload acak), yang tidak lagi berlaku.

## Pemeriksaan yang lulus

- **47 pengujian otomatis** (`python -B -m unittest discover -s tests`):
  - 16 pengujian protokol YAFS dengan fixture kecil: adapter bandwidth (double conversion
    ditolak), latensi optimizer sama dengan trace untuk satu link dan multihop tanpa antrean,
    request lokal yang belum selesai masuk denominator, deadline pending dan missed dibedakan,
    drain window dan kasus tanpa emisi, seed source reproducible, budget dan riwayat
    best-fitness, pairing, effect size, dan koreksi Holm.
  - 31 pengujian model dan alat (termasuk peta keberhasilan, aturan pemilihan titik, dan batas analitis cloud 43,615 ms): koefisien cloud peka CPU, `cpu_rate`, deadline terkopel vs
    tetap, seed kamera runner, profil literatur (IPT 445/1.000/7.750/9.300), opsi topologi
    (`--l1-class`, `--cloud-pr`), fps jitter, baseline Nearest/MinLatency, diagnosis tanpa
    antrean, pengamanan pairing ablasi (desain, skenario, kode metrik, `instance_id` ganda,
    pasangan kurang), dan integrasi CLI dua run kecil lintas semua level.
- **Integritas YAFS:** `python -B -m runner.integrity` melaporkan 12 file `yafs/` tidak berubah
  (SHA-256 terhadap `SOURCE_MANIFEST.json`); diperiksa sebelum dan sesudah setiap eksperimen.
- **Kualitas kode:** `pyflakes` bersih pada semua folder kecuali `yafs/`.
- **Pembersihan `_common.py` tidak mengubah hasil:** pada 28 kasus (10 algoritma, 3 mode cloud,
  dua skenario) hash alokasi, `best_fitness` (9 digit), dan jumlah evaluasi identik sebelum dan
  sesudah.

## Topologi hierarkis

Dengan manifest sintetis `data/cameras_SYNTHETIC.csv` (46 kamera, 16 persimpangan, 4 zona):
L1 = 16, L2 = 4, L3 = 1, cloud = 1 (22 node), 41 link, graf terhubung, dan `Topology.load` YAFS
asli memuatnya. Konversi BW memakai `config.units.engine_topology` (bytes/ms dibagi 1e6).

## Estimasi optimizer vs trace YAFS

Beban sangat rendah (fps x0,05), latensi estimasi (`_calc_times`) vs latensi trace:

| Kasus | Request | Hasil |
| --- | --- | --- |
| 1 modul, Random | 184 | 70 request tanpa tumpang tindih: selisih 0,000000 ms. 32 request menyimpang (sampai ~12 ms), semuanya tumpang tindih dengan request lain; tidak ada yang lebih cepat dari estimasi. |
| 4 modul, GA | 736 | 566 request lebih lambat dari estimasi (sampai ~66 ms); tidak ada request bebas tumpang tindih. |

Penyimpangan berasal dari antrean link native YAFS (antrean CPU modul nol; 2730 dari 3128 baris
link memiliki `buffer > 0`). Estimasi optimizer adalah batas bawah tanpa antrean. Skrip
pembandingnya tidak ada di repositori, dan pengujian ini memakai profil parameter lama.

## Integrasi (simulasi YAFS)

| Batch | Konfigurasi | Simulasi |
| --- | --- | --- |
| Smoke A-E | Profil lama (kelas Hailo, empat modul, fps 8-12 acak); desain `app-layering`, `fps-intensity`, `fps-fixed-deadline`; 1 run, budget 30-60 | 121 |
| Smoke F | **Profil literatur** (DET saja, `accel_B`, fps 10), `fps-fixed-deadline` 7 level, 1 run, Greedy/Nearest/MinLatency/GA/Random, budget 60, emisi 2000 ms, drain 2000 ms; varian utama, `--l1-class cpu_B`, dan `--cloud-pr 100` | 105 |
| Smoke G | Konfigurasi utama dengan 8 level fps (x0,5-x12), 1 run, Greedy/Nearest/MinLatency/GA/Random, budget 60, emisi 2000 ms, drain 2000 ms | 40 |

Semua 266 simulasi selesai tanpa error, dan `analysis.constraint_analysis` berhasil pada setiap
batch. Pemeriksaan: jumlah emisi sesuai perhitungan kasar, seluruh source di node L1, dan runner
tidak melaporkan penyimpangan emisi dari jadwal. Ini uji operasional, bukan bukti peringkat.

### Smoke F (profil literatur)

- **Utama** (DET saja, `accel_B`, cloud 25,6 ms): Nearest dan MinLatency mencapai on-time 1,000
  pada x0,5-x6; Greedy turun ke 0,06-0,49 mulai x3; GA dan Random 0,46-0,66 pada x4-x6.
- Kebutuhan komputasi pada x6 (46 x 930 x 6 = 256.680 inst/ms) masih di bawah kapasitas fog
  (353.400 inst/ms), jadi rentang x0,5-x6 belum menjenuhkan fog. **Smoke G (x0,5-x12)** mencapai
  saturasi: Nearest dan MinLatency 1,000 sampai x6, lalu 0,658 (x8), 0,517/0,462 (x10), dan runtuh
  ke 0,006 (x12); Greedy, GA, dan Random sudah turun pada x4 (0,06/0,66/0,63) dan juga runtuh
  pada x12 (0,01-0,03). Cloud yang diminta naik sampai 65% pada x12. 1 run, budget 60.
- **L1 `cpu_B`:** Nearest/MinLatency turun pada x5-x6 (0,957 dan 0,497), cloud 22% pada x6.
- **Cloud 100 ms:** penggunaan cloud 0 pada semua level; hasil lain mirip konfigurasi utama.
- Pada Smoke A-E (profil lama), antrean jaringan menyumbang 88-99% latensi pada fps tinggi dan
  antrean modul selalu 0; penurunan on-time terutama berasal dari beban, bukan dari deadline
  yang mengetat. `time_log.json` mencatat `cloud_pressure` (koefisien aktual, tekanan RAM/CPU).
- Ablasi v1 (`results/ablation-v1`, 5 run) memakai profil lama dan **tidak berlaku** untuk
  konfigurasi ini.

## Yang belum divalidasi

- **Manifest CityFlowV2 belum diekstrak**; seluruh hasil memakai manifest sintetis.
- **Placeholder:** payload DET (`FRAME_BYTES`) dan RAM modul, beban relatif CNT/REID/LPR terhadap
  DET, kelipatan kapasitas L2/L3/cloud (D), dan BW L3-cloud.
- **Benchmark penuh** (30 run, budget 3000), rentang level fps yang mencapai saturasi, dan
  ablasi ulang pada profil literatur belum dijalankan.
- **Tidak diperiksa ulang pada kode ini:** invarian emitted = completed + unfinished,
  on-time + miss + pending = emisi, ledger emisi identik antarstrategi, dan reprodusibilitas seed.
- Waktu emisi periodik dibulatkan ke ms terdekat (efek belum diukur); semua modul satu kamera
  mulai serentak (pengaruhnya pada antrean link belum dievaluasi); seed runner berbasis hash.

## Batas model YAFS

YAFS tidak membagi CPU antar-modul di node yang sama: tiap modul memiliki antrean FIFO sendiri
dan memakai IPT penuh. Kapasitas node hanya ditegakkan oleh placement (reservasi `cpu_rate`).
Model aplikasi adalah BOT (modul independen), bukan pipeline. Energi tetap proxy per-task.
