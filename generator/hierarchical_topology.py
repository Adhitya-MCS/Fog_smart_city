"""
Topologi hierarkis smart city dari manifest kamera (OpenFog RA Sec. 7.1).

  kamera (source di L1) -> L1 -> L2 -> L3 -> CLOUD, plus east-west L1 <-> L1 dalam zona.

Aturan (parameter di config/topology_params.py):
  - L1: satu per persimpangan (dipecah hanya jika max_cameras_per_l1 diberikan).
  - L2: satu per zona. L3: satu. CLOUD: satu.
  - East-west: tiap L1 ke EAST_WEST_NEIGHBORS tetangga terdekat dalam zona.
  - BW dalam bytes/ms (format legacy); loader runner membaginya dengan 1e6 untuk YAFS.
Topologi dibentuk sekali, lalu dibekukan untuk semua level stress test.
"""
import csv
import math
import random
from collections import OrderedDict
from pathlib import Path

from config import topology_params as topo_cfg

REQUIRED_COLUMNS = ["cam_id", "intersection_id", "zone_id", "lat", "lon"]


def load_cameras(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column(s) {missing}")
        cams = [dict(row, lat=float(row["lat"]), lon=float(row["lon"])) for row in reader]
    if len({c["cam_id"] for c in cams}) != len(cams):
        raise ValueError(f"{path}: duplicate cam_id")
    return sorted(cams, key=lambda c: c["cam_id"])


def _distance_m(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(math.sqrt(h))


def _node(node_id, tier, hw):
    cls = topo_cfg.NODE_CLASSES[hw]
    return {"id": node_id, "IPT": int(round(topo_cfg.IPT_REF * cls["speedup"])),
            "RAM": cls["RAM"], "type": tier, "hw": hw}


def _link(s, d, cls_key):
    lc = topo_cfg.LINK_CLASSES[cls_key]
    return {"s": s, "d": d, "PR": lc["PR"], "BW": lc["BW"], "class": cls_key}


def generate_hierarchical_topology(cameras, seed=42, max_cameras_per_l1=None):
    """Return (topology_json, camera_id -> L1 node id)."""
    rng = random.Random(seed)

    by_intersection = OrderedDict()
    for cam in sorted(cameras, key=lambda c: (c["zone_id"], c["intersection_id"], c["cam_id"])):
        by_intersection.setdefault(cam["intersection_id"], []).append(cam)

    groups = []
    for cams in by_intersection.values():
        step = max_cameras_per_l1 or len(cams)
        groups.extend(cams[i:i + step] for i in range(0, len(cams), step))

    n_l1 = len(groups)
    l1b = set(rng.sample(range(n_l1), int(round(topo_cfg.L1B_SHARE * n_l1))))

    topology = {"entity": [], "link": []}
    camera_to_l1, l1_zone, l1_pos = {}, {}, {}

    for node_id, group in enumerate(groups):
        node = _node(node_id, "L1", "L1b" if node_id in l1b else "L1a")
        node["zone"] = group[0]["zone_id"]
        node["cameras"] = [c["cam_id"] for c in group]
        topology["entity"].append(node)
        camera_to_l1.update({c["cam_id"]: node_id for c in group})
        l1_zone[node_id] = group[0]["zone_id"]
        l1_pos[node_id] = (sum(c["lat"] for c in group) / len(group),
                           sum(c["lon"] for c in group) / len(group))

    next_id = n_l1
    zone_to_l2 = {}
    for zone in sorted(set(l1_zone.values())):
        node = _node(next_id, "L2", "L2")
        node["zone"] = zone
        topology["entity"].append(node)
        zone_to_l2[zone] = next_id
        next_id += 1

    l3_id, cloud_id = next_id, next_id + 1
    topology["entity"].append(_node(l3_id, "L3", "L3"))
    cloud = dict(topo_cfg.CLOUD_ATTRS, id=cloud_id)
    topology["entity"].append(cloud)

    for l1, zone in l1_zone.items():
        topology["link"].append(_link(l1, zone_to_l2[zone], "L1-L2"))

    east_west = set()
    for l1, zone in l1_zone.items():
        peers = sorted((p for p, z in l1_zone.items() if z == zone and p != l1),
                       key=lambda p: _distance_m(l1_pos[l1], l1_pos[p]))
        east_west.update((min(l1, p), max(l1, p)) for p in peers[:topo_cfg.EAST_WEST_NEIGHBORS])
    topology["link"].extend(_link(s, d, "L1-L1") for s, d in sorted(east_west))

    topology["link"].extend(_link(l2, l3_id, "L2-L3") for l2 in zone_to_l2.values())
    topology["link"].append(_link(l3_id, cloud_id, "L3-CLOUD"))

    return topology, camera_to_l1


if __name__ == "__main__":
    import json
    import sys
    topo, mapping = generate_hierarchical_topology(load_cameras(Path(sys.argv[1])))
    counts = {}
    for e in topo["entity"]:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print("nodes:", counts, "| links:", len(topo["link"]), "| cameras:", len(mapping))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(topo, indent=2))
