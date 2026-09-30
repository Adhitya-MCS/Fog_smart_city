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

import operator
import networkx as nx
from config import topology_params as topo_cfg
from config import app_params as app_cfg
from config import users_params as user_cfg


def generate_topology(seed=42, num_fog_nodes=None, ba_degree=None):
    print("Generating topology...")

    random.seed(seed)
    num_fog_nodes = num_fog_nodes if num_fog_nodes is not None else topo_cfg.NUM_FOG_NODES
    ba_degree = ba_degree if ba_degree is not None else topo_cfg.BARABASI_ALBERT_DEGREE
    if num_fog_nodes <= ba_degree:
        raise ValueError(
            f"num_fog_nodes must be greater than ba_degree "
            f"({num_fog_nodes} <= {ba_degree})"
        )
    fog_graph = nx.barabasi_albert_graph(
        n=num_fog_nodes,
        m=ba_degree,
        seed=seed,
    )
    
    cloud_id = num_fog_nodes  # 10

    # Gateway selection by betweenness centrality
    centrality_no_order = nx.betweenness_centrality(fog_graph, weight="weight")
    centrality_sorted = sorted(
        centrality_no_order.items(),
        key=operator.itemgetter(1),
        reverse=True
    )
    
    num_cfg = max(1, int(num_fog_nodes * topo_cfg.PERCENTAGE_OF_CLOUD_GATEWAYS))
    num_fg = int(num_fog_nodes * topo_cfg.PERCENTAGE_OF_GATEWAYS)
    
    # CFG = top nodes by centrality (highest)
    cloud_fog_gateways = {centrality_sorted[i][0] for i in range(num_cfg)}
    # FG = bottom 25% (lowest centrality)
    fog_gateways = {
        centrality_sorted[id_dev][0]
        for id_dev in range(len(centrality_sorted) - num_fg, len(centrality_sorted))
        if id_dev >= 0
    }
    
    # Build topology
    topology = {"entity": [], "link": []}
    
    # Fog nodes (id 0..9) with type FOG | FG | CFG
    for node_id in fog_graph.nodes():
        fog_node = topo_cfg.get_fog_node_attrs(node_id)
        if node_id in cloud_fog_gateways:
            fog_node["type"] = "CFG"
        elif node_id in fog_gateways:
            fog_node["type"] = "FG"
        else:
            fog_node["type"] = "FOG"
        topology["entity"].append(fog_node)
    
    # Cloud node (id=10)
    cloud_node = topo_cfg.CLOUD_ATTRS.copy()
    cloud_node["id"] = cloud_id
    topology["entity"].append(cloud_node)
    
    # Fog-to-fog links (s, d in 0..9)
    for edge in fog_graph.edges():
        link = topo_cfg.get_fog_link_attrs()
        link["s"] = edge[0]
        link["d"] = edge[1]
        topology["link"].append(link)
    
    # CFG-to-cloud links
    for cfg_node in cloud_fog_gateways:
        link = topo_cfg.CLOUD_LINK_ATTRS.copy()
        link["s"] = cfg_node
        link["d"] = cloud_id
        topology["link"].append(link)
    
    print(f"  - Created {len(topology['entity'])} nodes (fog 0..{num_fog_nodes - 1}, cloud {cloud_id})")
    print(f"  - Created {len(topology['link'])} links")
    print(f"  - Gateways (centrality): {num_cfg} CFG, {num_fg} FG")
    
    return topology


def generate_applications(seed=42, num_apps=None, app_model_type=None):
    random.seed(seed)

    total = num_apps if num_apps is not None else app_cfg.NUM_APPLICATIONS
    model_type = app_model_type or app_cfg.APP_MODEL_TYPE
    print(f"Generating {total} applications (Model: {model_type})...")
    
    applications = []

    for app_id in range(total):
        # Generate DAG based on APP_MODEL_TYPE
        dag = app_cfg.generate_app_dag(model_type)
        
        deadline = app_cfg.get_app_deadline()
        
        # App structure (YAFS format)
        app = {
            "id": app_id,
            "name": str(app_id),
            "deadline": deadline,
            "HwReqs": 1,
            "MaxReqs": 200,
            "MaxLatency": deadline,
            "transmission": [],
            "module": [],
            "message": []
        }
        
        i = app_id
        module_name = lambda n: str(i) + "_" + str(n)
        edge_number = 0

        # =========================================================================
        # FIX: Generate attributes ONCE per module to ensure consistency
        # =========================================================================
        module_attrs = {}
        for n in dag.nodes():
            module_attrs[n] = app_cfg.get_service_attrs()

        # =========================================================================
        # 1) CREATE MODULES (Fixed: Added instructions, deadline)
        # =========================================================================
        for n in dag.nodes():
            attrs = module_attrs[n]
            app["module"].append({
                "id": n,
                "name": module_name(n),
                "IPT": attrs["instructions"],
                "RAM": attrs["RAM"],
                "instructions": attrs["instructions"],
                "bytes": attrs["bytes"],                 # Keep for YAFS compatibility
                "output_bytes": attrs["output_bytes"],   # response/result size (uplink, Apat Res)
                # Deadline is application-level (shared by all its services), matching
                # the reference (Azimzadeh 2022, Table 3 has only an app deadline) AND
                # the analysis SLA check (which groups by app deadline). This keeps the
                # optimizer's deadline (module dl) consistent with the reported SLA.
                "deadline": deadline,
                "type": "MODULE"
            })


        # =========================================================================
        # 2) HANDLE BOT (Bag of Tasks) vs DDF (Data Distribution Flow)
        # =========================================================================
        if model_type == 'BOT':
            # BOT: Tasks are independent (no edges in DAG).
            # Request-response model [Apat et al., 2024]: each module receives a request
            # from the User ("None"), computes, and sends a small RESULT back to an
            # actuator co-located at the requester (source gateway). The actuator is a
            # sink; it is NOT placed by the optimizer (fixed at source in build_problem).
            for n in dag.nodes():
                attrs = module_attrs[n]
                req_msg = f"M.USER.APP.{i}_{n}"
                resp_msg = f"R.APP.{i}_{n}"
                act_name = f"{i}_{n}_ACT"

                # Request: User -> task module (downlink, Apat Req)
                app["message"].append({
                    "id": edge_number,
                    "name": req_msg,
                    "s": "None",
                    "d": module_name(n),
                    "instructions": attrs["instructions"],
                    "bytes": attrs["bytes"]
                })
                edge_number += 1

                # Response: task module -> actuator (uplink, Apat Res); small result, no compute
                app["message"].append({
                    "id": edge_number,
                    "name": resp_msg,
                    "s": module_name(n),
                    "d": act_name,
                    "instructions": 0,
                    "bytes": attrs["output_bytes"]
                })
                edge_number += 1

                # Task module: receives request, emits response
                app["transmission"].append({
                    "module": module_name(n),
                    "message_in": req_msg,
                    "message_out": resp_msg
                })
                # Actuator: sink at the requester (receives the result back)
                app["transmission"].append({
                    "module": act_name,
                    "message_in": resp_msg
                })
                # Actuator module definition (sink). Fixed at the source gateway in
                # build_problem via "source_message"; excluded from the chromosome.
                app["module"].append({
                    "id": 1_000_000 + n,
                    "name": act_name,
                    "IPT": 1,
                    "RAM": 1,
                    "instructions": 0,
                    "bytes": 0,
                    "output_bytes": 0,
                    "deadline": deadline,
                    "type": "ACTUATOR",
                    "source_message": req_msg
                })

        else:
            # DDF / Workflow: Tasks have dependencies (edges in DAG)
            # Reverse edges (YAFS requirement)
            edge_list = list(dag.edges())
            dag.remove_edges_from(edge_list)
            dag.add_edges_from((v, u) for u, v in edge_list)
            
            # Source = first in topological order after reverse
            topo_order = list(nx.topological_sort(dag))
            source_node = topo_order[0]
            
            # 2a) Source message: User -> Source Module
            src_attrs = module_attrs[source_node]
            app["message"].append({
                "id": edge_number,
                "name": "M.USER.APP." + str(i),
                "s": "None",
                "d": module_name(source_node),
                "instructions": src_attrs["instructions"],
                "bytes": src_attrs["bytes"]
            })
            edge_number += 1
            
            # Transmissions out of source node
            for o in dag.edges():
                if o[0] == source_node:
                    app["transmission"].append({
                        "module": module_name(source_node),
                        "message_in": "M.USER.APP." + str(i),
                        "message_out": str(i) + "_(" + str(o[0]) + "-" + str(o[1]) + ")"
                    })
            
            # 2b) Edge messages: Module -> Module
            for n in dag.edges():
                u, v = n[0], n[1]
                # FIX: Use attributes of the DESTINATION module (v) for the message
                dest_attrs = module_attrs[v] 
                
                app["message"].append({
                    "id": edge_number,
                    "name": str(i) + "_(" + str(u) + "-" + str(v) + ")",
                    "s": module_name(u),
                    "d": module_name(v),
                    "instructions": dest_attrs["instructions"],
                    "bytes": dest_attrs["bytes"]
                })
                edge_number += 1
                
                # Transmissions out of destination module
                dest_node = v
                for o in dag.edges():
                    if o[0] == dest_node:
                        app["transmission"].append({
                            "module": module_name(dest_node),
                            "message_in": str(i) + "_(" + str(u) + "-" + str(v) + ")",
                            "message_out": str(i) + "_(" + str(o[0]) + "-" + str(o[1]) + ")"
                        })
            
            # 2c) Sink nodes: no outgoing edges
            for n in dag.nodes():
                if dag.out_degree(n) == 0:
                    for m in dag.edges():
                        if m[1] == n:
                            app["transmission"].append({
                                "module": module_name(n),
                                "message_in": str(i) + "_(" + str(m[0]) + "-" + str(m[1]) + ")"
                            })
                            break

        applications.append(app)
    
    print(f"  - Created {len(applications)} applications")
    
    return applications


def generate_users(topology, applications, seed=42):
    random.seed(seed)
    
    print(f"Generating users/sources (1 per task)...")
    
    users = {"sources": []}
    
    # Only FG (fog gateway) nodes host users
    gateway_nodes = [
        entity["id"] for entity in topology["entity"]
        if entity.get("type") == "FG"
    ]
    
    if not gateway_nodes:
        gateway_nodes = [
            entity["id"] for entity in topology["entity"]
            if entity.get("type") != "CLOUD"
        ]
    
    # Build per-app: message name and app_name for sources
    app_info = []
    for app in applications:
        source_messages = [msg for msg in app["message"] if msg["s"] == "None"]
        if not source_messages:
            continue
        
        # FIX: For BOT, there are multiple "None" messages per app (one per task).
        # YAFS expects exactly 1 source trigger per app definition, OR we iterate all of them.
        # Standard YAFS behavior: 1 source triggers 1 message. For BOT, we assign 1 source per task.
        for msg in source_messages:
            app_info.append({
                "app_id": app["id"],
                "app_name": str(app["id"]),
                "message_name": msg["name"],
            })
    
    if not app_info:
        print("  - No apps with source messages, skipping users")
        return users
    
    # Per-app lambda [200–1000] ms — Table 4: "Application request rate 1–5 per second"
    random.seed(seed)

    # 1 source per message (handles both BOT's multiple messages and DDF's single message)
    for idx, info in enumerate(app_info):
        node_id = gateway_nodes[idx % len(gateway_nodes)]
        users["sources"].append({
            "id_resource": node_id,
            "app": info["app_name"],
            "message": info["message_name"],
            "lambda": user_cfg.get_user_request_rate(),
        })
    
    print(f"  - Created {len(users['sources'])} user sources (on FG gateways)")
    
    return users


def main():
    # Create scenarios directory
    scenarios_dir = Path(__file__).parent.parent / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    
    # Set seed for reproducibility
    SEED = 42
    
    # Generate topology
    topology = generate_topology(seed=SEED)
    topo_file = scenarios_dir / "networkDefinition.json"
    with open(topo_file, 'w') as f:
        json.dump(topology, f, indent=2)
    print(f"Saved: {topo_file}")
    
    # Generate applications
    applications = generate_applications(seed=SEED)
    app_file = scenarios_dir / "appDefinition.json"
    with open(app_file, 'w') as f:
        json.dump(applications, f, indent=2)
    print(f"Saved: {app_file}")
    
    # Generate users
    users = generate_users(topology, applications, seed=SEED)
    user_file = scenarios_dir / "usersDefinition.json"
    with open(user_file, 'w') as f:
        json.dump(users, f, indent=2)
    print(f"Saved: {user_file}")
    
    print("\n" + "=" * 60)
    print("Generation completed!")
    print("=" * 60)
    print("\nNext step: Run generate_placements.py to create allocation files.")


if __name__ == "__main__":
    main()