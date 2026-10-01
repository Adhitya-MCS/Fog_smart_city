# Constraint aware benchmark dengan YAFS tetap utuh

Benchmark penempatan layanan (placement) fog-cloud hierarkis untuk video analytics smart city
(kamera -> L1 -> L2 -> L3 -> cloud, OpenFog RA Sec. 7.1), dengan stress test beban pada topologi
beku. Seluruh perubahan ada di **lapisan eksperimen**; 12 file dalam `yafs/` identik byte demi
byte dengan YAFS lokal yang dipakai (diverifikasi oleh `runner.integrity`). Tidak ada perubahan
engine, monkey-patch, subclass simulator, shared CPU scheduler baru, atau penggantian aturan
antrean link.

Landasan identitas simulator adalah hash kode YAFS lokal yang Anda gunakan.
Dokumen ini tidak mengklaim seluruh file lokal identik dengan setiap revisi branch
upstream YAFS3.1. Bekukan commit upstream yang digunakan dalam publikasi, disertai
hash kode lokal pada `SOURCE_MANIFEST.json`.

## Instalasi dan pemeriksaan

Python 3.11+; diuji memakai dependency yang tercatat di manifest setiap eksperimen.

```bash
cd constraint-aware-new
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -B -m runner.integrity
python -B -m unittest discover -s tests -v
```

`runner.integrity` memverifikasi daftar file dan SHA-256 seluruh sumber YAFS.
Pembuatan `__pycache__` oleh Python diabaikan oleh pemeriksa; gunakan `-B` untuk
menghindarinya. Isi kode sumber YAFS tidak pernah ditulis oleh pipeline.

## Jalankan eksperimen

Uji kecil:

```bash
python -B -m runner.run_experiment --output results/my-smoke \
  --manifest data/cameras_SYNTHETIC.csv --runs 5 --budget 70 \
  --duration 500 --drain-time 1000
python -B -m analysis.constraint_analysis results/my-smoke
```

Konfigurasi eksperimen utama:

```bash
python -B -m runner.run_experiment --output results/main-v1 \
  --manifest data/cameras_SYNTHETIC.csv --topology-seed 42 --runs 30 --budget 3000 \
  --duration 10000 --drain-time 10000 > main-v1.log 2>&1
python -B -m analysis.constraint_analysis results/main-v1
```

Benchmark utama belum dijalankan. Run berurutan menghindari kompetisi antarworker saat
mengukur runtime placement. Output harus folder baru; hasil yang ada tidak ditimpa. Hanya
routing native `hop_aware` dan model BOT request-response yang divalidasi.

## Komponen lapisan eksperimen

| Komponen | Perilaku |
| --- | --- |
| Konfigurasi | BW kanonis dalam bytes/ms; adapter membagi 1e6 untuk engine tanpa mengubah input asli |
| Optimizer | Jalur minimum-hop mengikuti YAFS; transmisi dijumlahkan per hop, propagasi dihitung pergi-pulang; antrean link tidak dimodelkan (batas bawah) |
| Trafik | Source periodik per (kamera, modul), fase awal acak per kamera, replay waktu integer ms |
| Population | Replay lewat API `deploy_source`; emisi dicatat setelah source loop mengirim dan dibandingkan dengan jadwal |
| Runner | Source dihentikan di akhir jendela emisi; satu `Sim.run` mencakup emisi + drain |
| Analisis | Completion dari respons aktuator; denominator dari ledger emisi; unfinished, deadline missed, dan deadline pending dibedakan |
| Repair | Skor marginal lokal: latensi, hop, headroom, deadline, dan penalti cloud adaptif (`max(RAM, CPU)`) |
| Fairness | Budget evaluasi fitness yang sama; jumlah aktual, runtime, riwayat konvergensi, dan aktivitas repair disimpan |
| Baseline | Greedy (IPT tertinggi), Nearest (hop terdekat ke sumber), MinLatency (estimasi latensi terendah), semuanya dengan pengecekan RAM/CPU dan fallback cloud; Random memakai best-of-budget |
| Statistik | Pairing per instance ID, signed rank-biserial, koreksi Holm per metrik; ablasi dan diagnosis di bawah |

YAFS tidak berubah: eksekusi CPU native per modul dan antrean link native yang mengikutsertakan
propagasi. Reservasi CPU berupa laju (`cpu_rate`, jika tidak ada `instructions/deadline`).
PSO/GWO/WOA/HHO adalah adaptasi diskrit khusus proyek, bukan implementasi kanonis optimizer
kontinu; mutasi HHO dinamai segment mutation, bukan sampling Levy.

## Kontrak satuan

Satu unit waktu YAFS ditetapkan menjadi **1 ms**. Payload bytes, IPT instructions/ms,
deadline dan inter-arrival ms, propagation ms, RAM MB.

Rumus engine tetap `payload / (BW_parameter * 1e6)`. Karena itu bandwidth fisik
75.000 bytes/ms diberi parameter engine 0,075. Parameter 0,075 tersebut **tidak
berarti klaim 0,075 Mbps**; ia merupakan adapter numerik yang mengikuti rumus
engine dan clock eksperimen. Topology kanonis tetap menyimpan 75.000.

Uji satu link: payload 3.000.000 bytes membutuhkan transmisi 40 ms; propagation
10 ms menghasilkan latency link 50 ms. Request dan response memakai perjalanan
terpisah. Uji multihop juga membandingkan langsung estimasi optimizer dengan trace
YAFS tanpa antrean. Queueing saat trafik bertambah tetap sepenuhnya milik YAFS.

## Desain stress test (`config/users_params.py`)

| Desain | Peran | Level | Deadline |
| --- | --- | --- | --- |
| `fps-fixed-deadline` | **eksperimen utama** (default) | DET saja, fps x 0,5 ... 12 | tetap = 100 ms (interval 10 FPS) |
| `fps-intensity` | tambahan: "selesai sebelum frame berikutnya" | DET saja, fps x 0,5 ... 12 | 1000/fps (mengecil saat fps naik) |
| `fps-fixed-deadline-4layers` | tambahan sintetis | 4 modul independen, fps x 0,5 ... 12 | tetap = 100 ms |
| `app-layering` | tambahan sintetis: jenis layanan | 1-4 modul, fps nominal | 1000/fps |

`fps-intensity` mengubah beban dan SLA sekaligus; `fps-fixed-deadline` hanya mengubah beban
sehingga pengaruh saturasi dapat dipisahkan dari pengetatan deadline.

## Protokol dan peta keberhasilan

`PROTOCOL.md` menetapkan RQ, metrik, ambang (on-time >= 0,95 dan < 0,50), tahap eksplorasi vs
konfirmasi dengan seed terpisah, dan aturan pemilihan titik. Eksplorasi: `sh scripts/run_exploration.sh OUT`
(beban x PR cloud x kelas L1 x 4 algoritma, 3 run; dapat dilanjutkan). `python -m analysis.regions OUT/regions OUT`
menulis `regions.csv` (peta per kondisi, algoritma, dan level, dengan interval bootstrap atas run) dan
`confirmation_points.json` (titik konfirmasi plus batas analitis PR cloud).

## Diagnosis penyebab degradasi

```bash
python -B -m analysis.diagnosis results/main-v1      # menulis results/main-v1/diagnosis/
```

Per request selesai, latensi dipecah menjadi jaringan ideal (transmisi + propagasi dari trace
link), antrean jaringan (teramati dikurangi ideal), tunggu modul, dan waktu proses. Per tier
(L1/L2/L3/cloud) dilaporkan reservasi CPU statis (`Σ cpu_rate / IPT`) berdampingan dengan beban
CPU runtime (waktu sibuk / jendela emisi; YAFS tidak membagi CPU, nilai > 1 berarti node
menjalankan pekerjaan konkuren melebihi IPT-nya), jumlah node dengan beban runtime > 1, dan jumlah
layanan di cloud. Keluaran: `diagnosis_runs.csv` dan `diagnosis_summary.csv`.

## Profil parameter dan skenario sensitivitas

Node mewakili **kelas kemampuan**, bukan perangkat tertentu. Label sumber ada di komentar
`config/*.py`: L = literatur, T = turunan, M = terukur, D = desain, placeholder = belum ada dasar.

- Waktu DET: 209 / 93 / 12 / 10 ms untuk `cpu_A` / `cpu_B` / `accel_A` / `accel_B` (Alqahtani et al.,
  arXiv 2409.16808, Sec. 3.3). `DET_INSTRUCTIONS = 93.000` (T) sehingga IPT ekuivalen 445 / 1.000 / 7.750 / 9.300.
  Pemetaan ini hanya mereproduksi waktu DET; jangan diterapkan ke modul lain.
- L1 utama `accel_B`; L2/L3/cloud = 3x / 10x / 10x IPT `accel_B` (D, "kapasitas layanan DET ekuivalen").
- FPS 10 seragam (D), PR L1-L2 dan L2-L3 2 ms (adaptasi iFogSim DCNSFog), PR L3-cloud 25,6 ms (M->T).
- Payload DET, RAM modul, BW L3-cloud, dan beban relatif CNT/REID/LPR masih placeholder.

Skenario sensitivitas lewat opsi runner: `--l1-class {cpu_A,cpu_B,accel_A,accel_B}`,
`--cloud-pr 100` (cloud 100 ms: tidak mungkin tepat waktu pada deadline 100 ms), dan `--fps-jitter 0.2`
(sebaran fps antarkamera). Reservasi analitis (mis. satu aliran DET = 930 inst/ms = 10% IPT `accel_B`)
bukan bukti kemampuan runtime atau jaminan deadline.

## Baseline dan ablasi

Gunakan topology, master seed, workload, run, horizon, dan budget identik.
Nama folder output dan pilihan komponen saja yang berubah. Seluruh varian memakai
YAFS yang sama dan diverifikasi sebelum/sesudah eksperimen.

Contoh pada desain utama (`fps-fixed-deadline`):

```bash
python -B -m runner.run_experiment --output results/full \
  --manifest data/cameras_SYNTHETIC.csv --runs 30 --budget 3000
python -B -m runner.run_experiment --output results/constant-cloud \
  --manifest data/cameras_SYNTHETIC.csv --runs 30 --budget 3000 --cloud-mode constant
python -B -m runner.run_experiment --output results/no-cloud \
  --manifest data/cameras_SYNTHETIC.csv --runs 30 --budget 3000 --cloud-mode none
python -B -m runner.run_experiment --output results/no-headroom \
  --manifest data/cameras_SYNTHETIC.csv --runs 30 --budget 3000 --alpha 0.5 --beta 0.5 --gamma 0
python -B -m runner.run_experiment --output results/random-init \
  --manifest data/cameras_SYNTHETIC.csv --runs 30 --budget 3000 --initialization random
```

Metode lengkap: bobot 1/3 masing-masing, cloud penalty adaptif, initialization mixed.
Cloud constant memakai koefisien 0,15. Ablasi headroom menormalkan ulang dua bobot
tersisa menjadi 0,5. Greedy tetap baseline greedy walaupun initialization random
dipilih; Random selalu tanpa greedy seed. Hard feasibility repair tetap aktif
supaya domain solusi tidak berubah. Belum ada opsi ablasi repair sederhana.

Semua strategi mendapat batas evaluasi yang sama; GA boleh selesai lebih awal
sesuai stopping rule aslinya. Actual count tersedia, bukan diasumsikan sama.
Cooling SA disesuaikan dengan budget; ini dicatat sebagai pengaturan eksperimen.
Budget evaluasi tidak menyamakan biaya repair atau runtime; keduanya dilaporkan.

Untuk perbandingan antaralgoritma, analyzer menyediakan peak-tier paired tests.
Ablasi antar-folder dijalankan dengan `python -m analysis.ablation OUT REF=... VARIAN=...`
(lihat `scripts/run_ablation.sh`). Alat ini menolak perbandingan bila desain, hash manifest kamera,
seed, budget, horizon, hash YAFS/kode hasil (`config`, `generator`, `placements`, `runner`), atau
berkas skenario per run berbeda, atau folder dianalisis dengan kode metrik/paket berbeda
(`analysis/analysis_manifest.json`, ditulis oleh `analysis.constraint_analysis`; folder tanpa berkas
ini ditolak), dan menolak `instance_id` ganda. Pasangan yang kurang dari 5 run
dilaporkan sebagai `insufficient paired runs`, bukan dihilangkan.
Dekomposisi `analysis.diagnosis` hanya untuk request yang selesai; `completed_share` menunjukkan
seberapa mewakili.

Untuk membandingkan **varian ablasi antar-folder**, pasangkan strategi yang sama
berdasarkan `instance_id` dalam `analysis/run_metrics.json`; helper
`analysis.statistik.paired_values` dapat digunakan. Analyzer CLI tidak otomatis
menggabungkan hasil beberapa folder atau mengklaim signifikansi ablasi.

## Keluaran dan interpretasi

- Root `manifest.json`: parameter, versi dependency, hash lapisan eksperimen dan YAFS.
- `apps_W/run_R/scenario/`: konfigurasi kanonis dan allocation tiap strategi.
- Tiap strategi: trace YAFS asli, verified `emissions.json`, `source_schedule.json`,
  metadata simulasi, allocation yang dipakai, `time_log.json`, dan `metrics.json`. `time_log.json` memuat `cloud_pressure`:
  koefisien cloud, tekanan RAM/CPU fog, dan jumlah layanan di cloud pada placement final.
- `analysis/run_metrics.json`, `summary.csv`, `pairwise_statistics.json`:
  ringkasan dan perbandingan statistik.

Semua ratio memakai skala 0–1. `null` berarti tidak terdefinisi.

`ontime_delivery_ratio` dan `deadline_miss_ratio` memakai seluruh emitted requests.
Unfinished dihitung sebagai miss hanya ketika deadline sudah terlewati; deadline
yang belum terlewati dilaporkan pending. Latency dan SLAV completed-only tetap
tersedia dengan nama yang menjelaskan denominatornya.

`max_observed_response_ms` adalah maksimum latency yang terlihat di jendela
pengamatan, bukan makespan seluruh cohort. `completion_by_emission_end` menunjukkan
completion sebelum drain. Penghentian YAFS eksklusif pada observation cutoff;
komputasi dengan projected `time_out >= cutoff` tidak dihitung selesai.

`requested_cloud_ratio` berdasarkan tujuan placement request, sedangkan
`completed_compute_cloud_ratio` berdasarkan task yang selesai komputasi.
Keduanya tidak otomatis membuktikan tingkat saturasi fisik fog.

`energy_proxy_j` mempertahankan bentuk proxy per-task berbasis durasi dan power,
dengan clipping komputasi pada cutoff. Ia **bukan energi fisik sistem**: periode
antar-module bisa overlap, network residence mencakup antrean, dan request yang
belum masuk komputasi tidak sepenuhnya terwakili. Jangan menyebutnya pengukuran
penghematan energi perangkat. Tidak ada model daya node baru yang dipaksakan
ke simulator.

## Batas ilmiah

Reservasi CPU adalah laju: `cpu_rate = instructions x laju kedatangan` pada generator
smart-city (sama dengan `instructions/deadline` bila deadline = interval frame). Ini aturan kelayakan placement,
bukan jaminan bahwa runtime YAFS menerapkan pembagian kapasitas CPU agregat yang
sama. Simulasi mempertahankan concurrency per module. Demikian pula propagation
tetap masuk native link scheduling. Efek kedua asumsi perlu dinyatakan di metode
serta limitations; tidak disembunyikan sebagai perubahan konfigurasi.

Trafik adalah stream per task, bukan satu trigger sinkron seluruh aplikasi.
Deadline aplikasi diterapkan ke masing-masing request task. Scope hanya BOT static,
tanpa migration atau failure source. Log emission mengandalkan kontrak native
source loop pada kode yang telah di-hash; pengujian memastikan pencatatan sesuai.

Uji integrasi bukan bukti threshold atau ranking ilmiah. Dibutuhkan benchmark
penuh, sensitivity horizon/drain, topology, bobot, serta baseline/ablasi yang sesuai.
Kode baru ini tidak menjamin hasil lama akan tetap sama.

Lihat `VALIDATION.md` untuk hasil validasi kode terbaru.
