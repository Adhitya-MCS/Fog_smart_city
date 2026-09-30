"""
Simulation Runner for YAFS 3.1
Loads scenario JSON files and runs simulation with selected placement.

This is RUN 2: Execute simulation with pre-generated configurations.
"""
import json
import sys
import argparse
from pathlib import Path
import logging.config

# Ensure project root on path for imports when run as script
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import networkx as nx

from yafs.core import Sim
from yafs.application import create_applications_from_json
from yafs.topology import Topology
from yafs.placement import JSONPlacement
from runner.json_population import JSONPopulation
from config.units import engine_topology
import hashlib
import math
from runner.path_routing import create_routing_strategy


AVAILABLE_PLACEMENTS = [n+'Placement' for n in ['Random','GA','PSO','GWO','WOA','HHO','SA','Greedy']]


def load_scenario(scenarios_dir: Path):
    """Load all scenario files."""
    with open(scenarios_dir / "networkDefinition.json") as f:
        topology_data = json.load(f)
    
    with open(scenarios_dir / "appDefinition.json") as f:
        applications_data = json.load(f)
    
    with open(scenarios_dir / "usersDefinition.json") as f:
        users_data = json.load(f)
    
    return topology_data, applications_data, users_data


def load_placement(scenarios_dir: Path, placement_name: str):
    """Load placement allocation file."""
    alloc_name = placement_name.replace("Placement", "")
    alloc_file = scenarios_dir / f"allocDefinition{alloc_name}.json"
    
    if not alloc_file.exists():
        raise FileNotFoundError(f"Placement file not found: {alloc_file}")
    
    with open(alloc_file) as f:
        placement_data = json.load(f)
    
    # YAFS uses app name as string (e.g. "0", "1"); ensure allocation matches
    for item in placement_data.get("initialAllocation", []):
        if "app" in item and not isinstance(item["app"], str):
            item["app"] = str(item["app"])
    
    return placement_data


def ensure_deployable_services(apps, applications_data):
    """
    Backfill service mappings required by YAFS JSONPlacement.

    BOT scenarios may model each task as a direct User -> Module message and
    may not include transmission rules. Older generated scenarios therefore
    produce Application.modules entries but no Application.services entries,
    which makes JSONPlacement fail with KeyError(module_name).
    """
    added = 0
    for app_def in applications_data:
        app_name = str(app_def["name"])
        app = apps[app_name]

        for message_def in app_def.get("message", []):
            module_name = message_def.get("d")
            if (
                message_def.get("s") == "None"
                and module_name in app.modules
                and module_name not in app.modules_src
                and module_name not in app.services
            ):
                message = app.get_message(message_def["name"])
                app.add_service_module(module_name, message)
                added += 1

    return added


def validate_placement(placement_data, apps, topology_data):
    """Fail early with a clear message when allocation and app services diverge."""
    node_ids = {entity["id"] for entity in topology_data.get("entity", [])}
    errors = []

    for index, item in enumerate(placement_data.get("initialAllocation", [])):
        app_name = str(item.get("app"))
        module_name = item.get("module_name")
        node_id = item.get("id_resource")

        if app_name not in apps:
            errors.append(f"allocation[{index}] references unknown app {app_name!r}")
            continue

        app = apps[app_name]
        if module_name not in app.services:
            available = ", ".join(sorted(app.services.keys())) or "<none>"
            errors.append(
                f"allocation[{index}] references module {module_name!r} for app "
                f"{app_name!r}, but Application.services has: {available}"
            )

        if node_id not in node_ids:
            errors.append(
                f"allocation[{index}] references unknown topology node {node_id!r}"
            )

    if errors:
        preview = "\n  - ".join(errors[:10])
        remaining = len(errors) - 10
        if remaining > 0:
            preview += f"\n  - ... and {remaining} more"
        raise ValueError(f"Invalid placement allocation:\n  - {preview}")


def run_simulation(
    placement_name: str,
    stop_time: int = 20000,
    routing: str = "hop_aware",
    results_dir=None,
    scenarios_dir=None,
    drain_time: float = 10000,
    run_seed: int = 1,
):
    """
    Run simulation with specified placement algorithm.

    Args:
        placement_name: Name of placement (e.g., "CNPlacement", "GAPlacement")
        stop_time: Simulation duration in time units
        routing: Path routing strategy
        results_dir: Override output directory (used by multi-instance runner)
        scenarios_dir: Override scenarios directory (used by multi-instance runner)
    """
    print("=" * 60)
    print(f"Running YAFS Simulation: {placement_name}")
    print("=" * 60)

    # Paths
    project_root = Path(__file__).parent.parent
    if scenarios_dir is None:
        scenarios_dir = project_root / "scenarios"
    scenarios_dir = Path(scenarios_dir)
    if results_dir is None:
        results_dir = project_root / "results" / placement_name
    results_dir = Path(results_dir)
    if routing != 'hop_aware':
        raise ValueError('Validated benchmark supports native hop_aware routing only')
    if not all(math.isfinite(x) for x in [stop_time,drain_time]) or stop_time<=0 or drain_time<0:
        raise ValueError('Invalid emission/drain window')
    if (results_dir/'sim_trace.csv').exists():
        raise FileExistsError('Refusing to overwrite an existing trace')
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Load scenario
    print("\nLoading scenario...")
    topology_data, applications_data, users_data = load_scenario(scenarios_dir)
    print(f"  ✓ Topology: {len(topology_data['entity'])} nodes, {len(topology_data['link'])} links")
    print(f"  ✓ Applications: {len(applications_data)} apps")
    print(f"  ✓ Users: {len(users_data['sources'])} sources")
    
    # Load placement
    print(f"\nLoading placement: {placement_name}...")
    placement_data = load_placement(scenarios_dir, placement_name)
    print(f"  ✓ Allocations: {len(placement_data['initialAllocation'])} modules")
    
    # Create topology
    print("\nCreating topology...")
    t = Topology()
    t.load(engine_topology(topology_data))
    print(f"  ✓ Topology loaded")
    
    # Create applications
    print("\nCreating applications...")
    apps = create_applications_from_json(applications_data)
    added_services = ensure_deployable_services(apps, applications_data)
    print(f"  ✓ {len(apps)} applications created")
    if added_services:
        print(f"  ✓ Backfilled {added_services} deployable BOT services")

    # Validate placement before YAFS starts the event loop.
    validate_placement(placement_data, apps, topology_data)
    
    # Create placement
    print(f"\nSetting up placement: {placement_name}...")
    placement = JSONPlacement(name=placement_name, json=placement_data)
    print(f"  ✓ Placement configured")
    
    # Create routing
    print("\nSetting up routing...")
    selectorPath = create_routing_strategy(routing)
    print(f"  ✓ Routing configured: {routing}")
    
    # Create simulator
    print("\nInitializing simulator...")
    result_file = str(results_dir / "sim_trace")
    s = Sim(t, default_results_path=result_file)
    print(f"  ✓ Simulator initialized")
    
    # Direct BOT request/response only. This does not alter Application or Sim.
    seen_sources=set()
    for item in users_data['sources']:
        key=(str(item['app']),item['message'])
        if key in seen_sources:raise ValueError('Duplicate source definition')
        seen_sources.add(key)
    for app in applications_data:
        for msg in app['message']:
            if msg['s']!='None' and not msg['d'].endswith('_ACT'):
                raise ValueError('Validated evaluation supports BOT request/response only')
    ledger,planned=[],[]
    observation_end=stop_time+drain_time
    for app_name in apps:
        population=JSONPopulation(name=f'Statical_{app_name}',json_data=users_data,
            run_seed=run_seed,emission_end=stop_time,observation_end=observation_end,
            ledger=ledger,planned=planned)
        s.deploy_app2(apps[app_name],placement,population,selectorPath)

    def stop_sources():
        yield s.env.timeout(stop_time)
        for source_des in list(s.alloc_source):
            s.stop_process(source_des)
    s.env.process(stop_sources())
    # One run only: native Sim.run initializes deployment and closes trace files.
    s.run(observation_end)
    expected=sum(len(source['times']) for source in planned)
    if len(ledger)!=expected:
        raise RuntimeError(f'Emission verification failed: {len(ledger)} != {expected}')
    for filename,value in [('emissions.json',ledger),('source_schedule.json',planned),
        ('networkDefinition.json',topology_data),('appDefinition.json',applications_data),
        ('allocation_used.json',placement_data),
        ('simulation_metadata.json',dict(engine='YAFS unchanged',clock='ms',
            emission_end_ms=stop_time,observation_end_ms=observation_end,run_seed=run_seed,
            expected_emissions=expected,verified_emissions=len(ledger),
            units='canonical BW bytes/ms; engine BW=canonical/1e6',
            core_sha256=hashlib.sha256((project_root/'yafs/core.py').read_bytes()).hexdigest()))]:
        (results_dir/filename).write_text(json.dumps(value,indent=2),encoding='utf-8')
    
    print("\n" + "=" * 60)
    print("Simulation Complete!")
    print("=" * 60)
    print(f"\nResults saved to: {results_dir}/")
    print(f"  - sim_trace.csv (module processing)")
    print(f"  - sim_trace_link.csv (network transmission)")
    
    return results_dir


def main():
    """Main simulation runner."""
    parser = argparse.ArgumentParser(description="Run YAFS fog computing simulation")
    parser.add_argument(
        "--placement",
        type=str,
        default="GAPlacement",
        choices=AVAILABLE_PLACEMENTS,
        help="Placement algorithm to use",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=20000,
        help="Simulation duration in time units",
    )
    parser.add_argument(
        "--routing",
        type=str,
        default="hop_aware",
        choices=["hop_aware"],
        help="Path routing strategy to use",
    )
    parser.add_argument(
        "--scenarios-dir",
        type=str,
        default=None,
        help="Path to scenario directory (defaults to ./scenarios)",
    )
    
    parser.add_argument("--drain",type=float,default=10000)
    parser.add_argument("--run-seed",type=int,default=1)
    args = parser.parse_args()

    try:
        run_simulation(args.placement, args.duration, args.routing, scenarios_dir=args.scenarios_dir,drain_time=args.drain,run_seed=args.run_seed)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()