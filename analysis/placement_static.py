"""
Static placement and scenario analysis.

This module analyzes allocDefinition*.json files together with
networkDefinition/appDefinition/usersDefinition to compute:
- APP, MOD
- FOG / CLOUD allocation (N / %)
- Idle fog nodes (N + list)
- Average RAM utilization (%)
- Approximate average network latency (ms) from gateways to modules
- Static energy proxy (Σ instr / IPT)

Intended to be run AFTER scenario + placements are generated,
but BEFORE running dynamic simulations.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

import networkx as nx


def _analyze_alloc_file(alloc_path: Path, net_data, app_data, users_data):
    """
    Analyze one allocation JSON.

    Returns a stats dict or None if file missing/invalid.
    """
    if not alloc_path.exists():
        return None
    try:
        with open(alloc_path, "r") as f:
            alloc_data = json.load(f)
    except Exception:
        return None

    allocations = alloc_data.get("initialAllocation", [])
    if not allocations:
        return None

    devices = {d["id"]: d for d in net_data["entity"]}
    cloud_nodes = [d["id"] for d in net_data["entity"] if d.get("type") == "CLOUD"]
    cloud_id = cloud_nodes[0] if cloud_nodes else 99999
    all_fog_ids = set(d["id"] for d in net_data["entity"] if d.get("type") != "CLOUD")

    # Build service info (app_id, ram, avg instructions per app)
    services_info = {}
    for app in app_data:
        avg_instr = 40000
        if app.get("message"):
            instrs = [m.get("instructions", 40000) for m in app["message"]]
            avg_instr = sum(instrs) / len(instrs) if instrs else 40000
        for mod in app.get("module", []):
            services_info[mod["name"]] = {
                "app_id": str(app["id"]),
                "ram": mod.get("RAM", 1),
                "instr": avg_instr,
            }

    # ------------------------------------------------------------------
    # Pre-compute static network latencies (approx.) for avg_latency
    # ------------------------------------------------------------------
    # Build graph with latency weights: PR + size/BW, size ≈ 3_000_000 bytes
    G = nx.Graph()
    for ent in net_data["entity"]:
        G.add_node(ent["id"])

    DEFAULT_SIZE = 3_000_000.0
    for link in net_data.get("link", []):
        bw = float(link.get("BW", 1))
        pr = float(link.get("PR", 0))
        weight = pr + DEFAULT_SIZE / bw
        G.add_edge(link["s"], link["d"], weight=weight)

    # Gateways per app (from usersDefinition.json)
    app_gateways = {}
    for src in users_data.get("sources", []):
        app_id = str(src.get("app"))
        gw = src.get("id_resource")
        if gw is None:
            continue
        app_gateways.setdefault(app_id, set()).add(gw)

    # Shortest-path latency from each gateway to all nodes
    gw_latencies = {}
    for gws in app_gateways.values():
        for gw in gws:
            if (gw, None) in gw_latencies:
                continue
            try:
                lengths = nx.single_source_dijkstra_path_length(G, gw, weight="weight")
            except Exception:
                lengths = {}
            for node_id, dist in lengths.items():
                gw_latencies[(gw, node_id)] = dist
            gw_latencies[(gw, None)] = 0.0

    algo_name = alloc_path.stem.replace("allocDefinition", "").replace(".json", "")

    # Primary placement only (first occurrence per (module_name, app)); ignore replicas
    seen_primary = set()
    primary_entries = []
    for item in allocations:
        key = (item.get("module_name"), str(item.get("app", "")))
        if key in seen_primary:
            continue
        seen_primary.add(key)
        primary_entries.append(item)

    num_primary = len(primary_entries)
    stats = {"file": algo_name, "num_apps": 0, "num_modules": num_primary}

    unique_apps = set()
    fog_count = cloud_count = 0
    node_ram_usage = defaultdict(int)
    used_fog_nodes = set()
    energy_total = 0.0

    total_lat = 0.0
    count_lat = 0

    for item in primary_entries:
        s_name = item.get("module_name")
        node = int(item.get("id_resource", -1))
        s_info = services_info.get(s_name)
        if s_info:
            unique_apps.add(s_info["app_id"])

        if node == cloud_id:
            cloud_count += 1
        else:
            fog_count += 1
            used_fog_nodes.add(node)
            if s_info:
                node_ram_usage[node] += s_info["ram"]

        dev = devices.get(node)
        if dev and s_info and dev.get("IPT", 0) > 0:
            energy_total += s_info["instr"] / dev["IPT"]

        # Approximate gateway-to-service network latency for this module
        if s_info:
            app_id = s_info["app_id"]
            gws = app_gateways.get(app_id, [])
            for gw in gws:
                dist = gw_latencies.get((gw, node))
                if dist is None:
                    continue
                total_lat += dist
                count_lat += 1

    stats["num_apps"] = len(unique_apps)
    stats["fog_alloc_count"] = fog_count
    stats["fog_alloc_pct"] = (fog_count / num_primary * 100) if num_primary else 0
    stats["cloud_alloc_count"] = cloud_count
    stats["cloud_alloc_pct"] = (cloud_count / num_primary * 100) if num_primary else 0

    idle_fog_ids = sorted(all_fog_ids - used_fog_nodes)
    stats["idle_fog_count"] = len(idle_fog_ids)
    stats["idle_fog_list"] = idle_fog_ids

    total_util_pct = 0
    for fid in all_fog_ids:
        cap = devices.get(fid, {}).get("RAM", 1)
        used = node_ram_usage.get(fid, 0)
        if cap > 0:
            total_util_pct += used / cap
    stats["avg_ram_pct"] = (total_util_pct / len(all_fog_ids)) * 100 if all_fog_ids else 0
    stats["energy"] = energy_total

    # Average network latency (ms) from gateways to placed modules
    stats["avg_latency"] = (total_lat / count_lat) if count_lat else 0.0

    return stats


def _print_allocation_table(stats_list):
    """Print summary table and idle fog detail."""
    if not stats_list:
        return
    header = (
        f"{'ALGO':<8} | {'APP':<3} | {'MOD':<4} | {'FOG (N / %)':<14} | "
        f"{'CLOUD (N / %)':<16} | {'IDLE FOG':<8} | {'RAM %':<8} | "
        f"{'LAT(ms)':<9} | {'ENERGY (J)':<12}"
    )
    print("\n" + "=" * len(header))
    print("🔍 Analisis Hasil Placement (Statik)")
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    for s in stats_list:
        fog_str = f"{s['fog_alloc_count']} / {s['fog_alloc_pct']:.0f}%"
        cld_str = f"{s['cloud_alloc_count']} / {s['cloud_alloc_pct']:.0f}%"
        lat_val = s.get("avg_latency", 0.0)
        row = (
            f"{s['file']:<8} | "
            f"{s['num_apps']:<3} | "
            f"{s['num_modules']:<4} | "
            f"{fog_str:<14} | "
            f"{cld_str:<16} | "
            f"{s['idle_fog_count']:<8} | "
            f"{s['avg_ram_pct']:<6.2f}%  | "
            f"{lat_val:<9.1f} | "
            f"{s['energy']:<12.1f}"
        )
        print(row)
    print("=" * len(header))

    print("\n[DETAIL] Daftar ID Fog Node yang Tidak Terpakai (Idle):")
    print("-" * 60)
    for s in stats_list:
        ids = s.get("idle_fog_list", [])
        if ids:
            ids_str = ", ".join(map(str, ids[:20]))
            if len(ids) > 20:
                ids_str += f", ... (+{len(ids) - 20} more)"
            print(f"  > {s['file']:<8} : [{ids_str}]")
        else:
            print(f"  > {s['file']:<8} : [Semua Fog Node Terpakai]")
    print("-" * 60)


def _write_allocation_excel(stats_list, output_path: Path):
    """Write summary to Excel (Summary sheet). Optional: pandas + openpyxl."""
    try:
        import pandas as pd
    except ImportError:
        print("⚠️  pandas tidak terpasang. Excel tidak dibuat. (pip install pandas openpyxl)")
        return
    try:
        df = pd.DataFrame(stats_list)
        # Reorder columns for Excel
        cols = [
            "file",
            "num_apps",
            "num_modules",
            "fog_alloc_count",
            "fog_alloc_pct",
            "cloud_alloc_count",
            "cloud_alloc_pct",
            "idle_fog_count",
            "avg_ram_pct",
            "avg_latency",
            "energy",
        ]
        df = df[[c for c in cols if c in df.columns]]
        df.rename(
            columns={
                "file": "ALGO",
                "num_apps": "APP",
                "num_modules": "MOD",
                "fog_alloc_count": "FOG_N",
                "fog_alloc_pct": "FOG_%",
                "cloud_alloc_count": "CLOUD_N",
                "cloud_alloc_pct": "CLOUD_%",
                "idle_fog_count": "IDLE_FOG",
                "avg_ram_pct": "RAM_%",
                "avg_latency": "LAT_MS",
                "energy": "ENERGY_J",
            },
            inplace=True,
        )
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(output_path, sheet_name="Summary", index=False, engine="openpyxl")
        print(f"\n✅ Laporan Excel: {output_path}")
    except Exception as e:
        print(f"\n⚠️  Excel gagal: {e}")


def run_allocation_analysis(scenarios_dir: Path | str):
    """
    Run static analysis on all allocDefinition*.json in scenarios_dir.
    Print table and write Excel to scenarios/allocation_analysis.xlsx.
    """
    scenarios_dir = Path(scenarios_dir)
    net_file = scenarios_dir / "networkDefinition.json"
    app_file = scenarios_dir / "appDefinition.json"
    users_file = scenarios_dir / "usersDefinition.json"
    if not net_file.exists() or not app_file.exists() or not users_file.exists():
        print(
            "⚠️  networkDefinition.json, appDefinition.json, atau usersDefinition.json tidak ada. Analisis dilewati."
        )
        return
    with open(net_file, "r") as f:
        net_data = json.load(f)
    with open(app_file, "r") as f:
        app_data = json.load(f)
    with open(users_file, "r") as f:
        users_data = json.load(f)

    alloc_files = sorted(scenarios_dir.glob("allocDefinition*.json"))
    stats_list = []
    for p in alloc_files:
        s = _analyze_alloc_file(p, net_data, app_data, users_data)
        if s:
            stats_list.append(s)

    if stats_list:
        _print_allocation_table(stats_list)
        _write_allocation_excel(stats_list, scenarios_dir / "allocation_analysis.xlsx")
    else:
        print("\n⚠️  Tidak ada file alokasi yang ditemukan untuk dianalisis.")


def main():
    """CLI entrypoint."""
    base_dir = Path(__file__).resolve().parent.parent
    scenarios_dir = base_dir / "scenarios"
    run_allocation_analysis(scenarios_dir)


if __name__ == "__main__":
    main()

