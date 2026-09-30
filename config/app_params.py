"""
Aplikasi video analytics smart city (OpenFog RA Sec. 7.1).
Satu kamera = satu aplikasi BOT; tiap lapisan analitik = satu modul yang menerima
request dari kamera (source di node L1). Lapisan ke-n = n modul pertama LAYER_ORDER.
Label sumber: literature, measured, design, placeholder.

Instruksi modul = t_ref_ms * IPT_REF, sehingga waktu proses di L1a = t_ref_ms.
Deadline aplikasi = interval frame (1000/fps); setiap modul harus selesai dalam
deadline itu (lihat users_params untuk fps).
"""
from config.topology_params import IPT_REF

# Perkiraan (design), bukan hasil ukur. Acuan: CityFlow >=960p (Tang et al., 2019, Sec. 3.1);
# OpenFog hlm. 96: 12 Mbps @ 30 fps = rata-rata 50 KB/frame video (batas bawah).
# Frame mandiri (JPEG/I-frame) diasumsikan lebih besar. Wajib diukur dari video CityFlow.
FRAME_BYTES = 150_000

# t_ref_ms: waktu layanan per request di L1a. in/out_bytes: request dan response.
MODULES = {
    "DET":  dict(t_ref_ms=8.3,  RAM=300, in_bytes=FRAME_BYTES, out_bytes=2_000),   # t_ref: literature (lemah, forum Hailo), wajib diukur; RAM: placeholder
    "CNT":  dict(t_ref_ms=3.0,  RAM=50,  in_bytes=2_000,       out_bytes=500),     # placeholder
    "REID": dict(t_ref_ms=12.0, RAM=250, in_bytes=40_000,      out_bytes=2_000),   # placeholder
    "LPR":  dict(t_ref_ms=15.0, RAM=300, in_bytes=FRAME_BYTES, out_bytes=500),     # pipeline: OpenFog hlm. 107; angka placeholder
}
LAYER_ORDER = ["DET", "CNT", "REID", "LPR"]   # design


def layer_modules(layers: int) -> list:
    if not 1 <= layers <= len(LAYER_ORDER):
        raise ValueError(f"layers={layers} must be between 1 and {len(LAYER_ORDER)}")
    return [dict(MODULES[k], kind=k, instructions=int(round(MODULES[k]["t_ref_ms"] * IPT_REF)))
            for k in LAYER_ORDER[:layers]]
