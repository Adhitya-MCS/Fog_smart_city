"""
Source kamera: periodik, 1000/fps ms, dengan fase awal acak per kamera.
Label sumber: L = literatur, D = desain.
"""
FPS_BASE = 10   # L -> D: mayoritas video CityFlow 10 FPS (Tang et al., 2019); semua kamera diseragamkan

# Level stress test pada topologi beku: (jumlah lapisan analitik, pengali fps, deadline tetap).
# deadline tetap = interval frame pada fps dasar kamera (tidak mengecil saat fps dikalikan).
_FPS_MULTIPLIERS = (0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0)   # D: mencakup saturasi agregat fog (sekitar x8)
DESIGNS = {
    # utama: satu modul DET, hanya beban yang berubah
    "fps-fixed-deadline":         [(1, m, True) for m in _FPS_MULTIPLIERS],
    # tambahan: beban dan SLA berubah bersamaan (deadline = 1000/fps)
    "fps-intensity":              [(1, m, False) for m in _FPS_MULTIPLIERS],
    # tambahan sintetis: empat modul independen (beban relatif modul lain placeholder)
    "app-layering":               [(1, 1.0, False), (2, 1.0, False), (3, 1.0, False), (4, 1.0, False)],
    "fps-fixed-deadline-4layers": [(4, m, True) for m in _FPS_MULTIPLIERS],
}


def level_label(design: str, level: tuple):
    """Nilai sumbu yang berubah; dipakai sebagai 'workload' pada hasil."""
    return level[0] if design == "app-layering" else level[1]
