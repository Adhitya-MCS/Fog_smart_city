"""
Protokol eksperimen (ditetapkan sebelum melihat hasil; lihat PROTOCOL.md).
Ambang adalah definisi operasional penelitian, bukan batas universal.
"""
ONTIME_TARGET = 0.95   # D: target tercapai bila on-time delivery >= 0,95
ONTIME_SEVERE = 0.50   # D: degradasi berat bila on-time delivery < 0,50

EXPLORATION_SEED, EXPLORATION_RUNS = 101, 5      # D: seed master terpisah dari konfirmasi
CONFIRMATION_SEED, CONFIRMATION_RUNS = 202, 30

CLOUD_PR_MS = (10.0, 25.6, 40.0, 44.0, 50.0, 100.0)   # D: mengapit batas kelayakan tanpa antrean (~43,6 ms)
L1_CLASSES = ("accel_B", "cpu_B")                      # D: kelas L1 utama dan pembanding CPU-only
ALGORITHMS = ("Greedy", "Nearest", "MinLatency", "GA", "PSO", "GWO", "WOA", "HHO", "SA", "Random")
BUDGET = 3000
