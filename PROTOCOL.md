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
| Eksplorasi | Grid penuh: 8 level fps x 6 PR cloud (10, 25,6, 40, 44, 50, 100 ms) x 2 kelas L1 (`accel_B`, `cpu_B`) x 10 algoritma, 5 run, budget 3000 (`scripts/run_exploration.sh`) | 101 |
| Konfirmasi | Titik terpilih oleh aturan di bawah ditambah titik beban rendah dan tinggi, 30 run | 202 (baru) |
| Ablasi | Kondisi representatif yang dipilih dengan aturan yang sama; cloud-mode (adaptive/constant/none) dan headroom aktif/nonaktif pada skenario identik | 202 |

Run eksplorasi boleh dipakai memilih titik tambahan, tetapi **tidak digabung** dengan run
konfirmasi (seed terpisah; seed run berbeda).

### Aturan pemilihan titik konfirmasi

Untuk setiap kondisi dan algoritma, urutkan level beban dan ambil: (a) level terendah dan tertinggi;
(b) untuk setiap persilangan ambang 0,95 dan 0,50 antara dua level berdekatan, kedua level yang
mengapit beserta titik tengahnya. Kondisi tanpa persilangan hanya mempertahankan titik ekstrem dan
**dilaporkan apa adanya**; ambang tidak digeser untuk menciptakan persilangan. Titik di luar
transisi dipertahankan untuk mendukung pernyataan seperti "heuristik cukup pada beban rendah".
Level tengah baru dijalankan lewat `--fps-multipliers`.

## Batas klaim

Manifest masih sintetis; payload DET, RAM modul, dan BW L3-cloud placeholder; modul adalah layanan
independen (bukan pipeline); YAFS tidak membagi CPU antar-modul; estimasi optimizer tanpa antrean
link. Hindari klaim *novel metaheuristic*, *dynamic placement*, *real-time guarantee*, dan optimasi
pipeline video. Signifikansi statistik menunjukkan bukti perbedaan, bukan kebaruan mekanisme;
kebaruan memerlukan pembandingan dengan formulasi terdahulu, dan konsistensi, besar efek, serta biaya
komputasi ikut dilaporkan.
