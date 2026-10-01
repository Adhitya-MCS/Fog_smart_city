# Protokol eksperimen

Ditetapkan 1 Oktober 2026, **sebelum** benchmark penuh dijalankan. Nilai ambang dan seed ada di
`config/protocol.py`; aturan pemilihan titik ada di `analysis/regions.py` dan tidak boleh diubah
setelah melihat hasil eksplorasi.

Judul kerja: *Characterizing Deadline Satisfaction of Service Placement in Hierarchical Fog-Cloud
Networks*.

## Pertanyaan penelitian

| RQ | Pertanyaan | Bukti |
| --- | --- | --- |
| RQ1 | Pada kondisi apa placement memenuhi target layanan? | Peta on-time delivery terhadap beban, PR cloud, dan kelas L1 |
| RQ2 | Kapan metaheuristik memberi manfaat dibanding heuristik sederhana? | Selisih berpasangan, besar efek, runtime dan budget pencarian |
| RQ3 | Bagaimana penalti cloud dan headroom mengubah wilayah itu? | Ablasi komponen pada skenario identik |

Hasil negatif (mis. "konstan sama baiknya dengan pressure-aware" atau "heuristik sederhana
mencukupi") tetap hasil, dibatasi pada kondisi yang diuji.

## Metrik dan definisi

- **Metrik utama:** `ontime_delivery_ratio` seluruh request teremisi.
- **Batas cloud:** `ontime_cloud_ratio` (on-time di antara request yang ditempatkan di cloud) dan
  `ontime_fog_ratio`, dijelaskan bersama `requested_cloud_ratio`. Sistem bisa memenuhi target
  walau PR melewati batas cloud bila cukup layanan tetap di fog; sebaliknya, tanpa offloading
  keberhasilan sistem tidak memberi informasi tentang kelayakan cloud.
- **Pending dan unfinished** selalu dilaporkan (`pending_share`, `unfinished_share`) agar batas
  pengamatan tidak dibaca sebagai kegagalan layanan.
- **Kategori (definisi operasional, bukan batas universal):** target tercapai bila on-time >= 0,95;
  target tidak tercapai bila < 0,95; degradasi berat bila < 0,50. Kurva kontinu dan interval
  ketidakpastian (bootstrap atas run) selalu disajikan; kesimpulan tidak boleh hanya bergantung pada
  kategori.
- **Unit analisis adalah run**, bukan request; request dari 30 run tidak digabung sebagai sampel
  independen.

## Batas analitis cloud

Batas **kelayakan tanpa antrean**, bukan batas operasional:

`PR_cloud_max = (D - T_proses - T_transmisi - T_propagasi_non_cloud) / 2`

dihitung dari estimator placement (`_calc_times`) pada PR cloud = 0, minimum atas sumber
(`analysis.regions.cloud_pr_max_ms`). Untuk deadline 100 ms, manifest sintetis, dan kelas L1
`accel_B`: **43,615 ms**. Jika estimasi sudah melampaui deadline, request pasti terlambat; jika masih
di bawah, request belum tentu tepat waktu karena antrean. Antrean tidak dijamin membuat batas
teramati lebih ketat (kurva keberhasilan sistem dapat non-monoton karena perubahan placement); hal
ini diuji, bukan diasumsikan. Jarak antara batas analitis dan batas teramati, beserta pengaruh
placement terhadapnya, adalah salah satu hasil yang dilaporkan.

## Tahapan

| Tahap | Cakupan | Seed master |
| --- | --- | --- |
| Eksplorasi | 8 level fps x 4 PR cloud (10, 25,6, 44, 100 ms) x 2 kelas L1 (`accel_B`, `cpu_B`) x 4 algoritma (Nearest, MinLatency, GA, Random) x 3 run = **768 simulasi**, budget 3000 (`scripts/run_exploration.sh`). Hanya untuk menemukan wilayah transisi dan memperkirakan biaya, **bukan** untuk peringkat atau signifikansi | 101 |
| Eskalasi | Sel eksplorasi yang run-nya berada di sisi berbeda dari ambang (ada run >= ambang dan ada run < ambang) dijalankan ulang dengan 5 run (seed tetap, run 1-3 identik, run 4-5 baru) | 101 |
| Konfirmasi | **Seluruh 10 algoritma** pada titik terpilih, 30 run | 202 (baru) |
| Ablasi | Kondisi representatif yang dipilih dengan aturan yang sama; cloud-mode (adaptive/constant/none) dan headroom aktif/nonaktif pada skenario identik | 202 |

Run eksplorasi dan eskalasi boleh dipakai memilih titik, tetapi **tidak digabung** dengan run
konfirmasi (seed master terpisah). Wilayah transisi empat algoritma eksplorasi belum tentu mewakili
algoritma lain, sehingga klaim peta lengkap dibatasi pada kondisi yang benar-benar diuji di
konfirmasi.

### Aturan pemilihan titik konfirmasi

Untuk setiap kondisi dan algoritma eksplorasi, urutkan level beban dan ambil: (a) level terendah dan
tertinggi, dan **titik tengah grid yang tetap (x6)**, selalu ikut, termasuk bila tidak ada
persilangan; (b) untuk setiap persilangan ambang 0,95 dan 0,50 antara dua level berdekatan, kedua
level yang mengapit beserta titik tengahnya. Titik dari semua algoritma eksplorasi digabung per
kondisi dan diterapkan ke seluruh 10 algoritma. Kondisi tanpa persilangan **dilaporkan apa adanya**;
ambang tidak digeser untuk menciptakan persilangan. Titik di luar transisi dipertahankan untuk
mendukung pernyataan seperti "heuristik cukup pada beban rendah". Level tengah baru dijalankan lewat
`--fps-multipliers`.

## Riwayat versi

| Versi | Perubahan | Alasan |
| --- | --- | --- |
| v1 (commit `89f7823`) | Grid 10 algoritma x 8 level x 6 PR x 2 kelas L1 x 5 run = 4.800 simulasi | Rancangan awal |
| v2 | 768 simulasi (4 algoritma, 4 PR, 3 run), konfirmasi seluruh algoritma, titik tengah tetap, aturan eskalasi run | Eksplorasi hanya mencari wilayah transisi; biaya terukur 67 detik per kondisi-run (4 algoritma x 8 level), sehingga 24 kondisi-run sekitar 27 menit. Direvisi **sebelum ada hasil eksplorasi dilihat**. |

## Batas klaim

Manifest masih sintetis; payload DET, RAM modul, dan BW L3-cloud placeholder; modul adalah layanan
independen (bukan pipeline); YAFS tidak membagi CPU antar-modul; estimasi optimizer tanpa antrean
link. Hindari klaim *novel metaheuristic*, *dynamic placement*, *real-time guarantee*, dan optimasi
pipeline video. Signifikansi statistik menunjukkan bukti perbedaan, bukan kebaruan mekanisme;
kebaruan memerlukan pembandingan dengan formulasi terdahulu, dan konsistensi, besar efek, serta biaya
komputasi ikut dilaporkan.
