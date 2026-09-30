"""
Scenario Generator for YAFS 3.1
Generates topology, applications, and users configuration as JSON files.
This is RUN 1: Generate all configurations before simulation.
"""

import json
import random
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from generator.hierarchical_topology import generate_hierarchical_topology, load_cameras
from config import app_params as app_cfg
from config import users_params as user_cfg


def generate_applications(cameras, layers, fps_multiplier=1.0, seed=42, fixed_deadline=False):
    """Satu aplikasi BOT per kamera; deadline = interval frame (1000/fps), atau interval fps dasar bila fixed_deadline."""
    rng = random.Random(seed)
    modules = app_cfg.layer_modules(layers)
    print(f"Generating {len(cameras)} applications ({layers} layers, fps x{fps_multiplier})...")

    applications = []
    for app_id, cam in enumerate(cameras):
        base_fps = rng.uniform(user_cfg.FPS_MIN, user_cfg.FPS_MAX)
        fps = base_fps * fps_multiplier
        deadline = 1000.0 / (base_fps if fixed_deadline else fps)
        app = {"id": app_id, "name": str(app_id), "deadline": deadline, "camera": cam["cam_id"], "fps": fps,
               "HwReqs": 1, "MaxReqs": 200, "MaxLatency": deadline,
               "transmission": [], "module": [], "message": []}
        edge_number = 0
        for n, spec in enumerate(modules):
            module_name = f"{app_id}_{n}"
            req_msg, resp_msg, act_name = f"M.USER.APP.{app_id}_{n}", f"R.APP.{app_id}_{n}", f"{app_id}_{n}_ACT"

            app["module"].append({"id": n, "name": module_name, "IPT": spec["instructions"], "RAM": spec["RAM"],
                                  "instructions": spec["instructions"], "cpu_rate": spec["instructions"] * fps / 1000.0,
                                  "bytes": spec["in_bytes"], "output_bytes": spec["out_bytes"], "deadline": deadline,
                                  "type": "MODULE", "kind": spec["kind"]})
            # Actuator = sink di node kamera; tidak dioptimasi (ditetapkan di build_problem).
            app["module"].append({"id": 1_000_000 + n, "name": act_name, "IPT": 1, "RAM": 1, "instructions": 0,
                                  "bytes": 0, "output_bytes": 0, "deadline": deadline,
                                  "type": "ACTUATOR", "source_message": req_msg})
            app["message"].append({"id": edge_number, "name": req_msg, "s": "None", "d": module_name,
                                   "instructions": spec["instructions"], "bytes": spec["in_bytes"]})
            app["message"].append({"id": edge_number + 1, "name": resp_msg, "s": module_name, "d": act_name,
                                   "instructions": 0, "bytes": spec["out_bytes"]})
            edge_number += 2
            app["transmission"].append({"module": module_name, "message_in": req_msg, "message_out": resp_msg})
            app["transmission"].append({"module": act_name, "message_in": resp_msg})
        applications.append(app)

    print(f"  - Created {len(applications)} applications")
    return applications


def generate_users(applications, camera_to_l1, seed=42):
    """Satu source per (kamera, modul) di node L1 kamera; periodik dengan fase acak per kamera."""
    rng = random.Random(seed)
    sources = []
    for app in applications:
        period_ms = 1000.0 / app["fps"]
        start_ms = rng.uniform(0.0, period_ms)
        for msg in app["message"]:
            if msg["s"] != "None":
                continue
            sources.append({"id_resource": camera_to_l1[app["camera"]], "app": app["name"],
                            "message": msg["name"], "lambda": period_ms,
                            "period_ms": period_ms, "start_ms": start_ms, "fps": app["fps"]})
    print(f"  - Created {len(sources)} user sources (on L1 nodes)")
    return {"sources": sources}


def main():
    """Tulis satu skenario: python -m generator.generate_scenario <manifest.csv> [layers] [fps_multiplier]"""
    scenarios_dir = Path(__file__).parent.parent / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    SEED = 42
    layers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    fps_multiplier = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    cameras = load_cameras(sys.argv[1])
    topology, camera_to_l1 = generate_hierarchical_topology(cameras, seed=SEED)
    applications = generate_applications(cameras, layers, fps_multiplier, seed=SEED)
    users = generate_users(applications, camera_to_l1, seed=SEED)
    for name, value in [("networkDefinition.json", topology), ("appDefinition.json", applications),
                        ("usersDefinition.json", users)]:
        (scenarios_dir / name).write_text(json.dumps(value, indent=2))
        print(f"Saved: {scenarios_dir / name}")
    print("\nNext step: python -m runner.run_experiment --manifest <manifest.csv> --output <new dir>")


if __name__ == "__main__":
    main()
