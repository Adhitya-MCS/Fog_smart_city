"""
Parameter topologi.

Bagian 1 (legacy): topologi acak Barabasi-Albert. Nilai dari [Pakpahan et al., 2025]
Table 1 dan [Azimzadeh et al., 2022] Table 3; CLOUD_IPT dan degree m adalah asumsi.
Bagian 2: topologi hierarkis smart city (L1/L2/L3/cloud), mengikuti OpenFog RA Sec. 7.1
dan IEEE 1934. Tiap nilai diberi label: datasheet, literature, measured, design, placeholder.
Satuan BW: bytes/ms (YAFS menerima BW/1e6, lihat runner). 1 Mbps = 125 bytes/ms.
"""
import random

# ============================ CLOUD CONFIGURATION ============================
CLOUD_RAM     = 999999999       # modeling simplification [Azimzadeh et al., 2022]: cloud "unlimited RAM"
CLOUD_IPT     = 10000           # modeling simplification (this work): large enough to never bottleneck; not cited to any source

CLOUD_ATTRS = {
    "IPT"         : CLOUD_IPT,
    "RAM"         : CLOUD_RAM,
    "type"        : "CLOUD",
}

# Link cloud cepat; PR sengaja > fog agar offload tidak "gratis" (this work).
CLOUD_LINK_ATTRS = {
    "BW": 75000,   # bytes/ms  [Pakpahan et al., 2025]
    "PR": 10,      # ms; > fog untuk menahan offload (assumption, this work)
}

# ============================= FOG CONFIGURATION =============================
# Semua nilai fog berikut -> [Pakpahan et al., 2025], Table 1.

NUM_FOG_NODES  = 100             # [Pakpahan et al., 2025]
BARABASI_ALBERT_DEGREE = 2       # assumption (this work); degree m tak disebut di Pakpahan

FOG_IPT_MIN = 1500   # inst/ms  [Pakpahan et al., 2025] (IPT 1500-3000)
FOG_IPT_MAX = 3000   # inst/ms

FOG_RAM_MIN = 10   # MB  [Pakpahan et al., 2025] (RAM 10-25)
FOG_RAM_MAX = 25   # MB

# ===================== LINK & GATEWAY CONFIGURATION =====================
PROPAGATION_TIME_MIN = 10   # ms  [Pakpahan et al., 2025] (Propagation Delay = 10)
PROPAGATION_TIME_MAX = 10   # ms
BANDWIDTH_MIN = 75000   # bytes/ms  [Pakpahan et al., 2025] (Bandwidth = 75000)
BANDWIDTH_MAX = 75000   # bytes/ms

PERCENTAGE_OF_CLOUD_GATEWAYS = 0.05   # [Azimzadeh et al., 2022] (CFG = 5% Fog nodes, Table 3)
PERCENTAGE_OF_GATEWAYS = 0.25         # [Azimzadeh et al., 2022] (FG = 25% Fog nodes, Table 3)

def get_fog_node_attrs(node_id: int) -> dict:
    return {
        "id"          : node_id,
        "IPT"         : random.randint(FOG_IPT_MIN, FOG_IPT_MAX),
        "RAM"         : random.randint(FOG_RAM_MIN, FOG_RAM_MAX),   
    }

def get_fog_link_attrs() -> dict:
    return {
        "PR": random.randint(PROPAGATION_TIME_MIN, PROPAGATION_TIME_MAX),
        "BW": random.randint(BANDWIDTH_MIN, BANDWIDTH_MAX),
    }


# ================= HIERARKI SMART CITY (OpenFog RA Sec. 7.1) =================
# Jumlah L1 = jumlah persimpangan, L2 = jumlah zona (dari manifest kamera).
# L3 = 1 (command center), cloud = 1. Topologi dibekukan pada beban nominal.
NUM_L3 = 1
NUM_CLOUD = 1

def mbps(x: float) -> float:
    return x * 125   # Mbps -> bytes/ms

IPT_REF = 1000   # inst/ms, design: IPT perangkat referensi L1a (Pi5 + Hailo-8L)

# speedup terhadap L1a; RAM = memori tersedia untuk layanan (MB)
NODE_CLASSES = {
    "L1a": {"speedup": 1.0,  "RAM": 6873},    # RAM measured (Pi5 8GB); speedup = referensi
    "L1b": {"speedup": 2.0,  "RAM": 6873},    # placeholder: rasio TOPS 26/13, wajib diukur
    "L2":  {"speedup": 3.0,  "RAM": 60000},   # placeholder: Jetson AGX Orin 64GB
    "L3":  {"speedup": 10.0, "RAM": 131072},  # placeholder; OpenFog hlm. 100: puluhan-ratusan GB
}
L1B_SHARE = 0.5   # design: porsi L1 yang memakai Hailo-8

# PR = RTT/2 (OpenFog tidak memberi delay)
LINK_CLASSES = {
    "L1-L1":    {"BW": mbps(1000),  "PR": 0.5},   # BW: OpenFog hlm. 100 (1/10 Gb); PR: Samani 2023
    "L1-L2":    {"BW": mbps(1000),  "PR": 0.5},   # BW: GbE Pi5 (OpenFog tak menyebut); PR: Samani 2023
    "L2-L3":    {"BW": mbps(10000), "PR": 1.0},   # BW: OpenFog hlm. 100 (10/100 GE); PR: placeholder
    "L3-CLOUD": {"BW": mbps(500),   "PR": 25.6},  # BW: placeholder; PR: measured (ping 51,23 ms / 2)
}
EAST_WEST_NEIGHBORS = 2   # design: tetangga L1 terdekat dalam zona
