"""
Source kamera: periodik, 1000/fps ms, dengan fase awal acak per kamera.
Label sumber: literature, design, placeholder.
"""
FPS_MIN = 8        # placeholder: -20% dari nominal 10 FPS (literature: CityFlow, mayoritas 10 FPS)
FPS_MAX = 12       # placeholder: +20% dari nominal

# Level stress test pada topologi beku: (jumlah lapisan analitik, pengali fps, deadline tetap).
# deadline tetap = interval frame pada fps dasar kamera (tidak mengecil saat fps dikalikan).
_FPS_MULTIPLIERS = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
DESIGNS = {
    "app-layering":       [(1, 1.0, False), (2, 1.0, False), (3, 1.0, False), (4, 1.0, False)],
    "fps-intensity":      [(4, m, False) for m in _FPS_MULTIPLIERS],   # deadline = 1000/fps: beban dan SLA berubah bersamaan
    "fps-fixed-deadline": [(4, m, True) for m in _FPS_MULTIPLIERS],    # hanya beban yang berubah
}


def level_label(design: str, level: tuple):
    """Nilai sumbu yang berubah; dipakai sebagai 'workload' pada hasil."""
    return level[0] if design == "app-layering" else level[1]
