"""
Parameter topologi hierarkis smart city (OpenFog RA Sec. 7.1, IEEE 1934).
Label sumber: datasheet, literature, measured, design, placeholder.
Satuan BW: bytes/ms (adapter YAFS membaginya dengan 1e6). 1 Mbps = 125 bytes/ms.
"""

CLOUD_RAM = 999999999   # "unlimited" [Azimzadeh et al., 2022]
CLOUD_IPT = 10000       # design: cukup besar agar cloud bukan bottleneck CPU

CLOUD_ATTRS = {"IPT": CLOUD_IPT, "RAM": CLOUD_RAM, "type": "CLOUD"}


def mbps(x: float) -> float:
    return x * 125


IPT_REF = 1000   # inst/ms, design: IPT perangkat referensi L1a (Pi5 + Hailo-8L)

# speedup terhadap L1a; RAM = memori tersedia untuk layanan (MB)
NODE_CLASSES = {
    "L1a": {"speedup": 1.0,  "RAM": 6873},    # RAM measured (Pi5 8GB)
    "L1b": {"speedup": 2.0,  "RAM": 6873},    # placeholder: rasio TOPS 26/13, wajib diukur
    "L2":  {"speedup": 3.0,  "RAM": 60000},   # placeholder: Jetson AGX Orin 64GB
    "L3":  {"speedup": 10.0, "RAM": 131072},  # placeholder; OpenFog hlm. 100: puluhan-ratusan GB
}
L1B_SHARE = 0.5   # design: porsi L1 yang memakai Hailo-8

# PR = RTT/2 (OpenFog tidak memberi delay)
LINK_CLASSES = {
    "L1-L1":    {"BW": mbps(1000),  "PR": 0.5},   # BW: OpenFog hlm. 100; PR: Samani 2023
    "L1-L2":    {"BW": mbps(1000),  "PR": 0.5},   # BW: GbE Pi5; PR: Samani 2023
    "L2-L3":    {"BW": mbps(10000), "PR": 1.0},   # BW: OpenFog hlm. 100; PR: placeholder
    "L3-CLOUD": {"BW": mbps(500),   "PR": 25.6},  # BW: placeholder; PR: measured (ping 51,23 ms / 2)
}
EAST_WEST_NEIGHBORS = 2   # design: tetangga L1 terdekat dalam zona
