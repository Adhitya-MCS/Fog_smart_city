"""
Aplikasi video analytics smart city (OpenFog RA Sec. 7.1).
Satu kamera = satu aplikasi BOT; tiap lapisan analitik = satu modul yang menerima
request langsung dari kamera (source di node L1), tanpa dependensi antarmodul.
Label sumber: L = literatur, T = turunan, D = desain, placeholder = belum ada dasar.

Eksperimen utama memakai satu modul (DET). Modul lain (CNT, REID, LPR) hanya untuk
eksperimen sintetis tambahan; beban relatifnya terhadap DET adalah placeholder.
Deadline aplikasi = interval frame atau tetap (lihat users_params dan generator).
"""

# T: waktu DET Pi 5 CPU 93 ms [Alqahtani et al., arXiv 2409.16808, Sec. 3.3] x 1.000 inst/ms.
# Angka ini beban komputasi ekuivalen yang mereproduksi waktu DET, bukan hitungan instruksi hardware.
DET_INSTRUCTIONS = 93_000

FRAME_BYTES = 150_000   # placeholder: frame >=960p terkompresi (CityFlow, Tang et al. 2019); batas bawah OpenFog 50 KB/frame; wajib diukur

# rel_load: instruksi relatif terhadap DET. in/out_bytes: request dan response.
MODULES = {
    "DET":  dict(rel_load=1.0,  RAM=300, in_bytes=FRAME_BYTES, out_bytes=2_000),   # beban: T; RAM, ukuran: placeholder
    "CNT":  dict(rel_load=0.36, RAM=50,  in_bytes=2_000,       out_bytes=500),     # placeholder
    "REID": dict(rel_load=1.45, RAM=250, in_bytes=40_000,      out_bytes=2_000),   # placeholder
    "LPR":  dict(rel_load=1.8,  RAM=300, in_bytes=FRAME_BYTES, out_bytes=500),     # pipeline: OpenFog hlm. 107; angka placeholder
}
LAYER_ORDER = ["DET", "CNT", "REID", "LPR"]   # design


def layer_modules(layers: int) -> list:
    if not 1 <= layers <= len(LAYER_ORDER):
        raise ValueError(f"layers={layers} must be between 1 and {len(LAYER_ORDER)}")
    return [dict(MODULES[k], kind=k, instructions=int(round(MODULES[k]["rel_load"] * DET_INSTRUCTIONS)))
            for k in LAYER_ORDER[:layers]]
