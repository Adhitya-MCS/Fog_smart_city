"""
Protokol eksperimen (ditetapkan sebelum melihat hasil; lihat PROTOCOL.md).
Ambang adalah definisi operasional penelitian, bukan batas universal.
"""
PROTOCOL_VERSION = "v2"   # v1: grid 4.800 simulasi (commit 89f7823); revisi sebelum ada hasil, lihat PROTOCOL.md

ONTIME_TARGET = 0.95   # D: target tercapai bila on-time delivery >= 0,95
ONTIME_SEVERE = 0.50   # D: degradasi berat bila on-time delivery < 0,50

EXPLORATION_SEED = 101      # D: seed master terpisah dari konfirmasi
CONFIRMATION_SEED = 202
EXPLORATION_RUNS = 3
ESCALATED_RUNS = 5          # sel yang run-nya berada di sisi berbeda dari ambang dijalankan ulang dengan 5 run
CONFIRMATION_RUNS = 30

CLOUD_PR_MS = (10.0, 25.6, 44.0, 100.0)   # D: dua kondisi layak, satu tepat di atas batas tanpa antrean (43,6152 ms), satu jauh
L1_CLASSES = ("accel_B", "cpu_B")         # D: kelas L1 utama dan pembanding CPU-only
EXPLORATION_ALGORITHMS = ("Nearest", "MinLatency", "GA", "Random")
CONFIRMATION_ALGORITHMS = ("Greedy", "Nearest", "MinLatency", "GA", "PSO", "GWO", "WOA", "HHO", "SA", "Random")
FIXED_MIDPOINT_LEVEL = 6.0   # D: titik tengah grid beban (x0,5-x12), selalu ikut konfirmasi
BUDGET = 3000
