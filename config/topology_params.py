"""
Parameter topologi hierarkis smart city (OpenFog RA Sec. 7.1, IEEE 1934).
Label sumber: L = literatur, T = turunan, M = terukur, D = desain, placeholder = belum ada dasar.
Satuan BW: bytes/ms (adapter YAFS membaginya dengan 1e6). 1 Mbps = 125 bytes/ms.
Node mewakili kelas kemampuan, bukan perangkat tertentu.
"""
from config.app_params import DET_INSTRUCTIONS

CLOUD_RAM = 999999999   # "unlimited" [Azimzadeh et al., 2022]


def mbps(x: float) -> float:
    return x * 125


# L: waktu inferensi DET (SSD MobileNet V1, tanpa pra/pasca-pemrosesan), ms
# [Alqahtani et al., arXiv 2409.16808, Sec. 3.3]. Pi 4/5 (CPU) dan Pi 4/5 + Coral TPU (akselerator).
EDGE_DET_MS = {"cpu_A": 209, "cpu_B": 93, "accel_A": 12, "accel_B": 10}
EDGE_RAM_MB = 4096   # L: RAM perangkat (Sec. 3.2), bukan RAM bebas; tidak membatasi pada workload ini
# T: IPT ekuivalen = DET_INSTRUCTIONS / waktu DET (inst/ms); hanya mereproduksi waktu DET.
EDGE_CLASSES = {k: {"IPT": round(DET_INSTRUCTIONS / t), "RAM": EDGE_RAM_MB} for k, t in EDGE_DET_MS.items()}
L1_CLASS = "accel_B"   # D: kelas L1 utama; kelas lain untuk pembanding

# D: kapasitas tier atas = kelipatan IPT accel_B (kapasitas layanan DET ekuivalen, bukan speedup terukur).
REFERENCE_IPT = EDGE_CLASSES["accel_B"]["IPT"]
TIER_MULTIPLE = {"L2": 3, "L3": 10, "CLOUD": 10}
NODE_CLASSES = {
    **EDGE_CLASSES,
    "L2": {"IPT": TIER_MULTIPLE["L2"] * REFERENCE_IPT, "RAM": 60000},    # RAM placeholder
    "L3": {"IPT": TIER_MULTIPLE["L3"] * REFERENCE_IPT, "RAM": 131072},   # RAM placeholder; OpenFog hlm. 100
}
CLOUD_ATTRS = {"IPT": TIER_MULTIPLE["CLOUD"] * REFERENCE_IPT, "RAM": CLOUD_RAM, "type": "CLOUD"}

CLOUD_PR_MS = 25.6   # M -> T: ping 51,23 ms / 2 (asumsi simetri); skenario lain: 100 ms (L -> D, iFogSim DCNSFog)

# PR satu arah (ms); propagasi dihitung dua arah pada request-response.
LINK_CLASSES = {
    "L1-L1":    {"BW": mbps(1000),  "PR": 0.5},          # BW: OpenFog hlm. 100; PR: Samani 2023
    "L1-L2":    {"BW": mbps(1000),  "PR": 2.0},          # BW: GbE; PR: L -> D (iFogSim DCNSFog)
    "L2-L3":    {"BW": mbps(10000), "PR": 2.0},          # BW: OpenFog hlm. 100; PR: L -> D (iFogSim DCNSFog)
    "L3-CLOUD": {"BW": mbps(500),   "PR": CLOUD_PR_MS},  # BW: placeholder
}
EAST_WEST_NEIGHBORS = 2   # D: tetangga L1 terdekat dalam zona
