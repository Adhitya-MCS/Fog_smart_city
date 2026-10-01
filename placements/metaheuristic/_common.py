"""Experiment-owned objective and repair for unchanged YAFS.
CPU admission remains instructions/deadline, as in the original research model.
This static reservation rule is not a model of shared runtime CPU scheduling.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx
import math
from config.units import physical_graph

# ---------------------------------------------------------------------------
# Default Weights -> weighted-sum TRI-objective [Apat et al., 2024], Eq.5 form
# (alpha+beta+gamma=1). Equal split (Apat's own a=b=g=1/3 convention), applied to the
# three QoS-native components: latency, hop-count, headroom (this work's substitution
# for Apat's original makespan/cost/energy -- cost was rejected outright by the author,
# energy demoted to a diagnostic-only metric; see module docstring for the full
# rationale). Revised from the prior bi-objective (alpha=beta=0.5, makespan+energy).
# ---------------------------------------------------------------------------
DEFAULT_ALPHA: float = 1.0 / 3.0   # latency (response time)
DEFAULT_BETA: float = 1.0 / 3.0    # hop count
DEFAULT_GAMMA: float = 1.0 / 3.0   # headroom (RAM/CPU margin)

# ---------------------------------------------------------------------------
# Penalty Configuration
#   PENALTY_WEIGHT (mu) -> bobot pelanggaran constraint [Apat et al., 2024], Eq.10-13.
#   CLOUD_PENALTY_BASE  -> adaptive cloud-fallback penalty = NOVELTY (this work); skala dengan
#   tekanan fog = max(RAM, CPU demand / kapasitas).
# ---------------------------------------------------------------------------
PENALTY_WEIGHT: float = 1.0
CLOUD_PENALTY_BASE: float = 0.15   # novelty (this work)

# ---------------------------------------------------------------------------
# Network -> [Pakpahan et al., 2025] (BW = 75000 bytes/ms)
# ---------------------------------------------------------------------------
DEFAULT_LINK_BW_BYTES_PER_MS: float = 75000.0

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlacementProblem:
    services: List[str]
    service_to_app: Dict[int, str]
    service_to_chain_idx: Dict[int, int]
    service_ram: Dict[int, float]
    service_cpu: Dict[int, float]
    service_inst: Dict[int, float]
    service_input_bytes: Dict[int, float]
    service_output_bytes: Dict[int, float]
    service_deadline: Dict[int, float]      # Seconds

    chains_info: List[Tuple[List[int], int]]

    fog_nodes: List[int]
    candidate_nodes: List[int]
    cloud_id: int
    node_ram: Dict[int, float]
    node_ipt: Dict[int, float]              # inst/ms
    ipt_max: float

    hop_dist: Dict[int, Dict[int, int]]
    path_bw_bytes_per_ms: Dict[int, Dict[int, float]]
    path_propagation_ms: Dict[int, Dict[int, float]]
    mean_pr_ms: float

    alpha: float = DEFAULT_ALPHA   # latency weight
    beta: float = DEFAULT_BETA     # hop-count weight
    gamma: float = DEFAULT_GAMMA   # headroom weight

    # Actuators (request-response, B-full): (module_name, app_id, source_node).
    # NOT in the chromosome; deployed fixed at the requester (source gateway).
    actuators: List[Tuple[str, str, int]] = field(default_factory=list)


@dataclass
class ServiceNormBounds:
    """Per-service min-max normalization bounds across all candidate nodes."""
    lat_min: float; lat_max: float   # latency (t_proc+t_comm), seconds
    hop_min: float; hop_max: float   # hop count



# ---------------------------------------------------------------------------
# Problem builder
# ---------------------------------------------------------------------------
def build_problem(
    topology, applications, users,
    alpha: float = DEFAULT_ALPHA, beta: float = DEFAULT_BETA, gamma: float = DEFAULT_GAMMA,
) -> PlacementProblem:
    entities = {e["id"]: e for e in topology["entity"]}
    cloud_id = _find_cloud_id(entities)

    G = physical_graph(topology)

    fog_nodes = [n for n in G.nodes() if n != cloud_id]
    candidate_nodes = list(fog_nodes) + ([cloud_id] if cloud_id in G.nodes() else [])

    node_ram, node_ipt = {}, {}
    for n in candidate_nodes:
        e = entities.get(n, {})
        is_cloud = (n == cloud_id)
        node_ram[n] = float(e.get("RAM", 4000.0))
        node_ipt[n] = float(e.get("IPT", 10000.0 if is_cloud else 2500.0))

    ipt_max = max(node_ipt.values()) if node_ipt else 1.0

    prs = [float(l.get("PR", 0.0)) for l in topology.get("link", []) if "PR" in l]
    mean_pr_ms = float(sum(prs) / len(prs)) if prs else 10.0

    services, service_to_app, service_ram, service_cpu, service_inst = [], {}, {}, {}, {}
    service_input_bytes, service_output_bytes, service_deadline = {}, {}, {}
    actuators: List[Tuple[str, str, int]] = []   # (name, app_id, source_node), fixed at requester

    for app in applications:
        app_id = str(app["id"])
        for mod in app.get("module", []):
            if mod.get("type") == "ACTUATOR":
                # Actuator = sink fixed at the requester (source gateway); NOT optimized.
                src = _get_message_source_node(app_id, mod.get("source_message", ""), users)
                if src is None: src = _get_app_source_node(app_id, users)
                if src is None: src = cloud_id
                actuators.append((mod["name"], app_id, src))
                continue
            idx = len(services)
            services.append(mod["name"])
            service_to_app[idx] = app_id
            service_ram[idx] = float(mod.get("RAM", 100.0))
            service_inst[idx] = float(mod.get("instructions", 0.0))

            # CPU demand as a RATE (inst/ms) -- NOVELTY (this work).
            # Consistent with node IPT and with YAFS semantics. Derived from
            # workload and deadline (paper Sec. 3.1):
            #   cpu_i = inst_i / dl_ms  ->  inst/ms  (same unit as IPT_n).
            # NOTE: a per-service "MIPS" attribute is intentionally NOT used: MIPS
            # does not exist in YAFS (see yafs/application.py: "Instead of MIPS, we
            # use IPT"). The previous `cpu_mips` field (10-100) was off-scale vs IPT
            # (1500-3000), which silently disabled the CPU capacity constraint.
            inst_i = float(mod.get("instructions", 0.0))
            dl_ms = float(mod.get("deadline", 1e12))
            # cpu_rate (inst/ms, = instructions x arrival rate) bila ada; jika tidak instructions/deadline.
            service_cpu[idx] = float(mod["cpu_rate"]) if "cpu_rate" in mod else ((inst_i / dl_ms) if 0.0 < dl_ms < 1e12 else 0.0)

            msg_bytes = float(mod.get("bytes", 0.0))
            service_input_bytes[idx] = float(mod.get("input_bytes", msg_bytes))
            service_output_bytes[idx] = float(mod.get("output_bytes", 0.0))  # response size (Apat Res)

            raw_dl = float(mod.get("deadline", 1e12))
            service_deadline[idx] = raw_dl / 1000.0 if raw_dl < 1e12 else 1e12

    name_to_idx = {name: i for i, name in enumerate(services)}

    chains_info = []
    for app in applications:
        app_id = str(app["id"])
        for chain, source_message in _get_module_chains(app):
            source = _get_message_source_node(app_id, source_message, users)
            if source is None: source = _get_app_source_node(app_id, users)
            if source is None and fog_nodes:  # fog_nodes already excludes cloud_id
                source = random.choice(fog_nodes)
            elif source is None:
                source = cloud_id
                
            indices = [name_to_idx[n] for n in chain if n in name_to_idx]
            if indices: chains_info.append((indices, source))

    service_to_chain_idx = {}
    for chain_idx, (indices, _) in enumerate(chains_info):
        for idx in indices: service_to_chain_idx[idx] = chain_idx

    hop_dist = dict(nx.all_pairs_shortest_path_length(G))

    path_bw, path_pr = {}, {}
    for u in G:
        path_bw[u], path_pr[u] = {}, {}
        for v in G:
            path=nx.shortest_path(G,source=u,target=v)
            links=[G[a][b] for a,b in zip(path,path[1:])]
            inverse_bw=sum(1.0/e['BW'] for e in links)
            path_bw[u][v]=1.0/inverse_bw if inverse_bw else float('inf')
            path_pr[u][v]=sum(e['PR'] for e in links)

    if any(not math.isfinite(w) or w<0 for w in (alpha,beta,gamma)) or alpha+beta+gamma<=0:
        raise ValueError('Weights must be finite, nonnegative and sum to a positive value')
    total_weight = alpha + beta + gamma
    if total_weight > 0:
        alpha_norm = alpha / total_weight
        beta_norm = beta / total_weight
        gamma_norm = gamma / total_weight
    else:
        alpha_norm, beta_norm, gamma_norm = 1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0

    return PlacementProblem(
        services=services, service_to_app=service_to_app,
        service_to_chain_idx=service_to_chain_idx,
        service_ram=service_ram, service_cpu=service_cpu, service_inst=service_inst,
        service_input_bytes=service_input_bytes,
        service_output_bytes=service_output_bytes,
        service_deadline=service_deadline,
        chains_info=chains_info, fog_nodes=fog_nodes, candidate_nodes=candidate_nodes,
        cloud_id=cloud_id, node_ram=node_ram, node_ipt=node_ipt, ipt_max=ipt_max,
        hop_dist=hop_dist, path_bw_bytes_per_ms=path_bw,
        path_propagation_ms=path_pr, mean_pr_ms=mean_pr_ms, alpha=alpha_norm, beta=beta_norm, gamma=gamma_norm,
        actuators=actuators,
    )


# ---------------------------------------------------------------------------
# Precompute Normalization Bounds
# ---------------------------------------------------------------------------
def precompute_normalization_bounds(prob: PlacementProblem) -> List[ServiceNormBounds]:
    bounds = []
    for i in range(len(prob.services)):
        lat_vals, hop_vals = [], []
        for j in prob.candidate_nodes:
            # Dengan model BOT murni, _calc_times tidak lagi bergantung pada chrom.
            # Sumber komunikasi selalu IoT source.
            t_proc, t_comm = _calc_times(i, j, prob)
            lat_vals.append(t_proc + t_comm)
            hop_vals.append(float(_get_hops(i, j, prob)))

        bounds.append(ServiceNormBounds(
            lat_min=min(lat_vals), lat_max=max(lat_vals),
            hop_min=min(hop_vals), hop_max=max(hop_vals),
        ))
    return bounds


# ---------------------------------------------------------------------------
# Internal Helper: Time Calculations (FIXED for strict BOT model)
# ---------------------------------------------------------------------------
def _calc_times(i: int, node: int, prob: PlacementProblem) -> Tuple[float, float]:
    """
    Computes processing and communication time.
    STRICT BOT MODEL: Services are independent. Communication ALWAYS originates 
    from the IoT edge device (dispatcher), never from a preceding microservice.
    """
    ipt = max(prob.node_ipt.get(node, 1.0), 1e-9)
    inst = prob.service_inst.get(i, 0.0)
    t_proc_ms = inst / ipt

    chain_idx = prob.service_to_chain_idx.get(i, -1)
    comm_src_node = node  # Default fallback if service has no chain info

    if chain_idx != -1:
        # Pure BOT: Always receive data from the IoT source node, 
        # ignoring sequence in the chain.
        _, iot_src_node = prob.chains_info[chain_idx]
        comm_src_node = iot_src_node

    bw_down = prob.path_bw_bytes_per_ms.get(comm_src_node, {}).get(node, 1.0)
    bw_up = prob.path_bw_bytes_per_ms.get(node, {}).get(comm_src_node, 1.0)

    in_bytes = prob.service_input_bytes.get(i, 0.0)
    out_bytes = prob.service_output_bytes.get(i, 0.0)

    t_comm_ms = 0.0
    if bw_down > 0 and bw_up > 0:
        t_comm_ms = (in_bytes / bw_down) + (out_bytes / bw_up)

    t_comm_ms += prob.path_propagation_ms[comm_src_node][node] + prob.path_propagation_ms[node][comm_src_node]

    # Convert ms to seconds for energy consistency
    t_proc = t_proc_ms / 1000.0
    t_comm = t_comm_ms / 1000.0
    return t_proc, t_comm


def _get_hops(i: int, node: int, prob: PlacementProblem) -> int:
    """Hop count from service i's IoT source to candidate node. Same comm_src_node
    derivation as _calc_times, kept separate so callers can use hop count on its own
    (e.g. as its own weighted objective term) without re-deriving t_proc/t_comm."""
    chain_idx = prob.service_to_chain_idx.get(i, -1)
    comm_src_node = node
    if chain_idx != -1:
        _, iot_src_node = prob.chains_info[chain_idx]
        comm_src_node = iot_src_node
    return prob.hop_dist.get(comm_src_node, {}).get(node, 0)


def _node_headroom(node: int, prob: PlacementProblem,
                    ram_load: float, cpu_load: float) -> float:
    """1 - the worse of a node's post-placement RAM/CPU utilization -- in [0, 1],
    higher is better (more slack). Cloud is unbounded -> always full headroom (1.0),
    so this term never penalizes cloud placements; the separate cloud-fallback
    penalty already discourages over-reliance on cloud."""
    if node == prob.cloud_id:
        return 1.0
    ram_cap = prob.node_ram.get(node, 0.0)
    cpu_cap = prob.node_ipt.get(node, 0.0)
    util_ram = (ram_load / ram_cap) if ram_cap > 0 else 0.0
    util_cpu = (cpu_load / cpu_cap) if cpu_cap > 0 else 0.0
    return 1.0 - max(util_ram, util_cpu)


# ---------------------------------------------------------------------------
# Tri-objective Cost Function — MINIMIZATION
# (V3 cleanup) Standalone compute_makespan / compute_energy / compute_objectives
# DIHAPUS: dead code, tak dipakai pipeline.
# ---------------------------------------------------------------------------
def _minmax(val: float, lo: float, hi: float) -> float:
    rng = hi - lo
    if rng < 1e-12: return 0.0
    return min(1.0, max(0.0, (val - lo) / rng))

def _compute_total_cost(
    chrom: List[int],
    prob: PlacementProblem,
    bounds: List[ServiceNormBounds],
    *,
    penalise_invalid: bool = True,
) -> float:
    """
    Computes total cost to be MINIMIZED by the search algorithms.
    Lower cost = Better placement.

    Tri-objective (QoS-native, revised 2026-09-07 -- see module docstring for the
    full rationale): alpha*latency + beta*hop_count + gamma*headroom, each
    per-service min-max normalized, alpha+beta+gamma=1.

    Provenance:
      - Weighted-sum tri-objective FORM, normalisasi min-max, constraint deadline
        -> [Apat et al., 2024] Eq. 5 (structure only; components substituted).
      - Hop-count component -> structurally [Pakpahan et al., 2025] Eq. 6 (their own
        GA fitness optimizes hop count directly).
      - Headroom component, adaptive cloud-fallback penalty (lambda_cloud)
        -> NOVELTY (this work).
    """
    cost = 0.0

    # --- Aggregate per-node RAM/CPU load (needed for the Headroom term below;
    # this replaces the old RAM/CPU soft-penalty block, confirmed dead code since
    # repair_chromosome already guarantees no node exceeds capacity by the time this
    # function runs -- see ALGORITHM_MECHANISM.md). ---
    node_ram_load: Dict[int, float] = {}
    node_cpu_load: Dict[int, float] = {}
    for i, node in enumerate(chrom):
        if node != prob.cloud_id:
            node_ram_load[node] = node_ram_load.get(node, 0.0) + prob.service_ram.get(i, 0.0)
            node_cpu_load[node] = node_cpu_load.get(node, 0.0) + prob.service_cpu.get(i, 0.0)

    # --- Base Tri-objective Cost ---
    for i, node in enumerate(chrom):
        t_proc, t_comm = _calc_times(i, node, prob)
        latency_ij = t_proc + t_comm
        hop_ij = _get_hops(i, node, prob)
        headroom_ij = _node_headroom(node, prob, node_ram_load.get(node, 0.0), node_cpu_load.get(node, 0.0))

        b = bounds[i]
        f_lat = _minmax(latency_ij, b.lat_min, b.lat_max)
        f_hop = _minmax(hop_ij, b.hop_min, b.hop_max)
        f_headroom_cost = 1.0 - headroom_ij   # minimize cost -> reward high headroom

        cost += prob.alpha * f_lat + prob.beta * f_hop + prob.gamma * f_headroom_cost

    # --- Constraint-Aware Penalties (Added to cost) ---
    if penalise_invalid:
        fog_ram = sum(prob.service_ram.get(i, 0.0) for i, node in enumerate(chrom) if node != prob.cloud_id)
        fog_cpu = sum(prob.service_cpu.get(i, 0.0) for i, node in enumerate(chrom) if node != prob.cloud_id)

        effective_cloud_penalty = cloud_coefficient(prob, fog_ram, fog_cpu)

        for i, node in enumerate(chrom):
            if node == prob.cloud_id:
                cost += effective_cloud_penalty

        # NOTE: the RAM/CPU capacity soft-penalty that used to live here was removed
        # 2026-09-07 -- confirmed dead code (repair_chromosome already guarantees
        # capacity feasibility before this function ever runs; empirically verified,
        # 0 violations in 600 trials). The Headroom term above is its active
        # replacement: a continuous, always-live signal for the same underlying
        # concern, instead of a penalty that could never fire.

        for i, node in enumerate(chrom):
            t_proc, t_comm = _calc_times(i, node, prob)
            total_t = t_proc + t_comm
            dl = prob.service_deadline.get(i, 1e12)
            if total_t > dl and dl > 0:
                cost += PENALTY_WEIGHT * ((total_t - dl) / dl)

    return cost


# ---------------------------------------------------------------------------
# Constraint checks
# ---------------------------------------------------------------------------
def evaluate_ram_valid(chrom: List[int], prob: PlacementProblem) -> bool:
    node_load: Dict[int, float] = {}
    for i, node in enumerate(chrom):
        if node == prob.cloud_id: continue
        node_load[node] = node_load.get(node, 0.0) + prob.service_ram.get(i, 0.0)
    return all(load <= prob.node_ram.get(n, 0.0) for n, load in node_load.items())

def evaluate_cpu_valid(chrom: List[int], prob: PlacementProblem) -> bool:
    node_load: Dict[int, float] = {}
    for i, node in enumerate(chrom):
        if node == prob.cloud_id: continue
        node_load[node] = node_load.get(node, 0.0) + prob.service_cpu.get(i, 0.0)
    return all(load <= prob.node_ipt.get(n, 0.0) for n, load in node_load.items())

# ---------------------------------------------------------------------------
# Chromosome helpers
# ---------------------------------------------------------------------------
def greedy_seed_chrom(prob: PlacementProblem) -> List[int]:
    if INITIALIZATION == 'random':
        return repair_chromosome(random_chrom(prob),prob,precompute_normalization_bounds(prob))
    # Encoding (index=module, value=node) & greedy/sort-match seed -> [Pakpahan et al., 2025].
    if not prob.services or not prob.fog_nodes or prob.cloud_id is None: return []
    ranked = sorted(prob.fog_nodes, key=lambda n: prob.node_ipt.get(n, 0.0), reverse=True)
    caps_ram = {n: float(prob.node_ram.get(n, 0.0)) for n in ranked}
    caps_cpu = {n: float(prob.node_ipt.get(n, 0.0)) for n in ranked}

    chrom: List[int] = []
    for i in range(len(prob.services)):
        ram = float(prob.service_ram.get(i, 1.0))
        cpu = float(prob.service_cpu.get(i, 1.0))

        chosen = prob.cloud_id
        for n in ranked:
            if caps_ram.get(n, 0.0) >= ram and caps_cpu.get(n, 0.0) >= cpu:
                chosen = n
                caps_ram[n] -= ram
                caps_cpu[n] -= cpu
                break
        chrom.append(chosen)
    return chrom

def _feasible_first_chrom(prob: PlacementProblem, key) -> List[int]:
    """Service by service: the fog node that fits (residual RAM and CPU) with the smallest key(i, node); cloud if none fits."""
    if not prob.services or not prob.fog_nodes or prob.cloud_id is None: return []
    left_ram = {n: float(prob.node_ram.get(n, 0.0)) for n in prob.fog_nodes}
    left_cpu = {n: float(prob.node_ipt.get(n, 0.0)) for n in prob.fog_nodes}
    chrom: List[int] = []
    for i in range(len(prob.services)):
        ram = float(prob.service_ram.get(i, 1.0))
        cpu = float(prob.service_cpu.get(i, 1.0))
        fits = [n for n in prob.fog_nodes if left_ram[n] >= ram and left_cpu[n] >= cpu]
        if fits:
            chosen = min(fits, key=lambda n: (key(i, n), n))
            left_ram[chosen] -= ram
            left_cpu[chosen] -= cpu
        else:
            chosen = prob.cloud_id
        chrom.append(chosen)
    return chrom


def nearest_feasible_chrom(prob: PlacementProblem) -> List[int]:
    """Baseline: fewest hops from the service's source, ties by estimated latency."""
    return _feasible_first_chrom(prob, lambda i, n: (_get_hops(i, n, prob), sum(_calc_times(i, n, prob))))


def min_latency_chrom(prob: PlacementProblem) -> List[int]:
    """Baseline: lowest estimated latency (t_proc + t_comm), ties by hops."""
    return _feasible_first_chrom(prob, lambda i, n: (sum(_calc_times(i, n, prob)), _get_hops(i, n, prob)))


def random_chrom(prob: PlacementProblem) -> List[int]:
    if not prob.services or not prob.candidate_nodes: return []
    return [random.choice(prob.candidate_nodes) for _ in range(len(prob.services))]

def repair_chromosome(
    chrom: List[int],
    prob: PlacementProblem,
    bounds: Optional[List[ServiceNormBounds]] = None,
) -> List[int]:
    """Sequential capacity repair with a marginal cost estimate.

    Feasible existing genes stay in place. Overflow candidates are ranked using
    tri-objective, deadline and adaptive cloud terms, including the headroom change
    of already assigned services. This remains a local repair, not a global solve.
    """
    if not chrom:
        return chrom
    loads_ram = {n: 0.0 for n in prob.candidate_nodes}
    loads_cpu = {n: 0.0 for n in prob.candidate_nodes}
    counts = {n: 0 for n in prob.candidate_nodes}
    repaired = []

    def cloud_cost(ram, cpu, count):
        return count * cloud_coefficient(prob, ram, cpu)

    def score(i, node):
        proc, comm = _calc_times(i, node, prob)
        latency = proc + comm
        b = bounds[i] if bounds else None
        lat_cost = _minmax(latency, b.lat_min, b.lat_max) if b else latency
        hop_cost = _minmax(_get_hops(i,node,prob), b.hop_min,b.hop_max) if b else _get_hops(i,node,prob)
        before = 1.0-_node_headroom(node,prob,loads_ram[node],loads_cpu[node])
        after = 1.0-_node_headroom(node,prob,loads_ram[node]+prob.service_ram[i],loads_cpu[node]+prob.service_cpu[i])
        headroom_delta = (counts[node]+1)*after-counts[node]*before
        dl = prob.service_deadline[i]
        deadline = PENALTY_WEIGHT*max(0.0,(latency-dl)/dl) if dl>0 else 0.0
        ram = sum(loads_ram[n] for n in prob.fog_nodes)
        cpu = sum(loads_cpu[n] for n in prob.fog_nodes)
        to_fog = node!=prob.cloud_id
        cloud_delta = (cloud_cost(ram+(prob.service_ram[i] if to_fog else 0.0), cpu+(prob.service_cpu[i] if to_fog else 0.0), counts[prob.cloud_id]+int(not to_fog))
                       -cloud_cost(ram, cpu, counts[prob.cloud_id]))
        return prob.alpha*lat_cost+prob.beta*hop_cost+prob.gamma*headroom_delta+deadline+cloud_delta

    for i, original in enumerate(chrom):
        def fits(n):
            return n==prob.cloud_id or (loads_ram[n]+prob.service_ram[i]<=prob.node_ram[n] and loads_cpu[n]+prob.service_cpu[i]<=prob.node_ipt[n])
        if original in prob.candidate_nodes and fits(original):
            chosen=original
        else:
            feasible=[n for n in prob.candidate_nodes if fits(n)]
            chosen=min(feasible,key=lambda n:(score(i,n),n))
        repaired.append(chosen)
        loads_ram[chosen]+=prob.service_ram[i]
        loads_cpu[chosen]+=prob.service_cpu[i]
        counts[chosen]+=1
    tracker = _active_budget.get()
    if tracker is not None:
        tracker.repair_calls += 1
        tracker.repaired_genes += sum(a!=b for a,b in zip(chrom,repaired))
    return repaired


def to_allocation(chrom: List[int], prob: PlacementProblem):
    alloc = [{"module_name": prob.services[i], "app": str(prob.service_to_app[i]),
              "id_resource": chrom[i]} for i in range(len(prob.services))]
    # Actuators (B-full): fixed at the requester (source gateway), not optimized.
    for act_name, app_id, src_node in prob.actuators:
        alloc.append({"module_name": act_name, "app": str(app_id), "id_resource": src_node})
    return alloc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _find_cloud_id(entities) -> int:
    for eid, edata in entities.items():
        if edata.get("type") == "CLOUD" or edata.get("model") == "cloud": return eid
    return max(entities.keys(), default=0)

def _get_app_source_node(app_id: str, users) -> Optional[int]:
    for src in users.get("sources", []):
        if src.get("app") == str(app_id): return src.get("id_resource")
    return None

def _get_message_source_node(app_id: str, message_name: str, users) -> Optional[int]:
    for src in users.get("sources", []):
        if src.get("app") == str(app_id) and src.get("message") == message_name:
            return src.get("id_resource")
    return None

def _get_module_chains(app) -> List[Tuple[List[str], str]]:
    next_mod: Dict[str, List[str]] = {}
    source_messages: List[Tuple[str, str]] = []
    for msg in app.get("message", []):
        if msg.get("s") == "None": 
            source_messages.append((msg["d"], msg["name"]))
        else: 
            next_mod.setdefault(msg["s"], []).append(msg["d"])
            
    if not source_messages:
        modules = [m["name"] for m in app.get("module", [])]
        return [(modules, "")]
        
    chains: List[Tuple[List[str], str]] = []
    for first, source_message in source_messages:
        stack = [[first]]
        while stack:
            path = stack.pop()
            last = path[-1]
            if last in next_mod:
                for child in next_mod[last]:
                    stack.append(path + [child])
            else:
                chains.append((path, source_message))
    return chains

CLOUD_MODE = 'adaptive'
INITIALIZATION = 'mixed'


def cloud_coefficient(prob, fog_ram_demand, fog_cpu_demand):
    if CLOUD_MODE == 'none': return 0.0
    if CLOUD_MODE == 'constant': return CLOUD_PENALTY_BASE
    ram_cap=sum(prob.node_ram[n] for n in prob.fog_nodes)
    cpu_cap=sum(prob.node_ipt[n] for n in prob.fog_nodes)
    if not ram_cap and not cpu_cap: return CLOUD_PENALTY_BASE
    pressure=max(fog_ram_demand/ram_cap if ram_cap else 0.0, fog_cpu_demand/cpu_cap if cpu_cap else 0.0)
    return CLOUD_PENALTY_BASE*max(0.1,1.0-pressure)

def cloud_pressure_report(chrom, prob):
    """Fog pressure and cloud coefficient of a final placement (for result logs)."""
    fog = [i for i, n in enumerate(chrom) if n != prob.cloud_id]
    ram = sum(prob.service_ram.get(i, 0.0) for i in fog)
    cpu = sum(prob.service_cpu.get(i, 0.0) for i in fog)
    ram_cap = sum(prob.node_ram[n] for n in prob.fog_nodes)
    cpu_cap = sum(prob.node_ipt[n] for n in prob.fog_nodes)
    return dict(cloud_mode=CLOUD_MODE, cloud_coefficient=cloud_coefficient(prob, ram, cpu),
                ram_pressure=ram / ram_cap if ram_cap else None, cpu_pressure=cpu / cpu_cap if cpu_cap else None,
                fog_ram_reserved=ram, fog_ram_capacity=ram_cap, fog_cpu_reserved=cpu, fog_cpu_capacity=cpu_cap,
                services=len(chrom), cloud_services=len(chrom) - len(fog))


from contextvars import ContextVar
_active_budget = ContextVar('fitness_budget', default=None)


class BudgetExhausted(Exception):
    pass


class EvaluationBudget:
    """Counts actual objective calls; preserves the best completed evaluation."""
    def __init__(self, limit):
        if limit <= 0:
            raise ValueError('Budget must be positive')
        self.limit=limit
        self.evaluations=0
        self.best_cost=float('inf')
        self.best_chrom=None
        self.problem=None
        self.history=[]
        self.repair_calls=0
        self.repaired_genes=0

    def __enter__(self):
        self.token=_active_budget.set(self)
        return self

    def __exit__(self,*args):
        _active_budget.reset(self.token)


def compute_total_cost(chrom, prob, bounds, *, penalise_invalid=True):
    tracker=_active_budget.get()
    if tracker is not None and tracker.evaluations>=tracker.limit:
        raise BudgetExhausted()
    value=_compute_total_cost(chrom,prob,bounds,penalise_invalid=penalise_invalid)
    if tracker is not None:
        tracker.evaluations+=1
        if value<tracker.best_cost:
            tracker.best_cost=value
            tracker.best_chrom=list(chrom)
            tracker.problem=prob
        tracker.history.append((tracker.evaluations,tracker.best_cost))
    return value
