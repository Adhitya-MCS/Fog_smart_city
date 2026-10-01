"""Objective, constraint checks, baselines, and repair for the placement benchmark (YAFS unchanged).

CPU admission is a static reservation (cpu_rate, inst/ms), not a model of shared runtime CPU.
Model: bag of independent services; every service communicates with its requester (the camera's
L1 node) and returns a small response (request-response, Apat et al., 2024).
"""
from __future__ import annotations

import math
import random
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx
from config.units import physical_graph

# Weighted-sum tri-objective [Apat et al., 2024] Eq. 5 form: latency, hop count, headroom.
DEFAULT_ALPHA: float = 1.0 / 3.0   # latency
DEFAULT_BETA: float = 1.0 / 3.0    # hop count
DEFAULT_GAMMA: float = 1.0 / 3.0   # headroom (RAM/CPU margin)

PENALTY_WEIGHT: float = 1.0        # deadline violation weight [Apat et al., 2024] Eq. 10-13
CLOUD_PENALTY_BASE: float = 0.15   # adaptive cloud-fallback penalty scale (this work)

CLOUD_MODE = 'adaptive'
INITIALIZATION = 'mixed'


@dataclass(frozen=True)
class PlacementProblem:
    services: List[str]
    service_to_app: Dict[int, str]
    service_source: Dict[int, int]          # requester node of each service
    service_ram: Dict[int, float]
    service_cpu: Dict[int, float]           # inst/ms reservation
    service_inst: Dict[int, float]
    service_input_bytes: Dict[int, float]
    service_output_bytes: Dict[int, float]
    service_deadline: Dict[int, float]      # seconds

    fog_nodes: List[int]
    candidate_nodes: List[int]
    cloud_id: int
    node_ram: Dict[int, float]
    node_ipt: Dict[int, float]              # inst/ms

    hop_dist: Dict[int, Dict[int, int]]
    path_bw_bytes_per_ms: Dict[int, Dict[int, float]]
    path_propagation_ms: Dict[int, Dict[int, float]]

    alpha: float = DEFAULT_ALPHA
    beta: float = DEFAULT_BETA
    gamma: float = DEFAULT_GAMMA

    # Actuators (module_name, app_id, source_node): response sinks fixed at the requester, not optimized.
    actuators: List[Tuple[str, str, int]] = field(default_factory=list)


@dataclass
class ServiceNormBounds:
    """Per-service min-max bounds over all candidate nodes."""
    lat_min: float; lat_max: float   # t_proc + t_comm, seconds
    hop_min: float; hop_max: float


def build_problem(
    topology, applications, users,
    alpha: float = DEFAULT_ALPHA, beta: float = DEFAULT_BETA, gamma: float = DEFAULT_GAMMA,
) -> PlacementProblem:
    if any(not math.isfinite(w) or w < 0 for w in (alpha, beta, gamma)) or alpha + beta + gamma <= 0:
        raise ValueError('Weights must be finite, nonnegative and sum to a positive value')
    total_weight = alpha + beta + gamma

    entities = {e["id"]: e for e in topology["entity"]}
    cloud_id = _find_cloud_id(entities)
    G = physical_graph(topology)

    fog_nodes = [n for n in G.nodes() if n != cloud_id]
    candidate_nodes = fog_nodes + [cloud_id]
    node_ram = {n: float(entities[n]["RAM"]) for n in candidate_nodes}
    node_ipt = {n: float(entities[n]["IPT"]) for n in candidate_nodes}

    services, service_to_app, service_source = [], {}, {}
    service_ram, service_cpu, service_inst = {}, {}, {}
    service_input_bytes, service_output_bytes, service_deadline = {}, {}, {}
    actuators: List[Tuple[str, str, int]] = []

    for app in applications:
        app_id = str(app["id"])
        request_message = {m["d"]: m["name"] for m in app["message"] if m["s"] == "None"}
        for mod in app["module"]:
            if mod["type"] == "ACTUATOR":
                actuators.append((mod["name"], app_id, _source_node(app_id, mod["source_message"], users)))
                continue
            idx = len(services)
            services.append(mod["name"])
            service_to_app[idx] = app_id
            service_source[idx] = _source_node(app_id, request_message[mod["name"]], users)
            service_ram[idx] = float(mod["RAM"])
            service_inst[idx] = float(mod["instructions"])
            # CPU reservation rate (inst/ms): cpu_rate if given, else instructions / deadline.
            service_cpu[idx] = float(mod["cpu_rate"]) if "cpu_rate" in mod else service_inst[idx] / float(mod["deadline"])
            service_input_bytes[idx] = float(mod["bytes"])
            service_output_bytes[idx] = float(mod["output_bytes"])
            service_deadline[idx] = float(mod["deadline"]) / 1000.0

    hop_dist = dict(nx.all_pairs_shortest_path_length(G))
    path_bw, path_pr = {}, {}
    for u in G:
        path_bw[u], path_pr[u] = {}, {}
        for v in G:
            path = nx.shortest_path(G, source=u, target=v)
            links = [G[a][b] for a, b in zip(path, path[1:])]
            inverse_bw = sum(1.0 / e['BW'] for e in links)
            path_bw[u][v] = 1.0 / inverse_bw if inverse_bw else float('inf')
            path_pr[u][v] = sum(e['PR'] for e in links)

    return PlacementProblem(
        services=services, service_to_app=service_to_app, service_source=service_source,
        service_ram=service_ram, service_cpu=service_cpu, service_inst=service_inst,
        service_input_bytes=service_input_bytes, service_output_bytes=service_output_bytes,
        service_deadline=service_deadline, fog_nodes=fog_nodes, candidate_nodes=candidate_nodes,
        cloud_id=cloud_id, node_ram=node_ram, node_ipt=node_ipt, hop_dist=hop_dist,
        path_bw_bytes_per_ms=path_bw, path_propagation_ms=path_pr,
        alpha=alpha / total_weight, beta=beta / total_weight, gamma=gamma / total_weight,
        actuators=actuators,
    )


def precompute_normalization_bounds(prob: PlacementProblem) -> List[ServiceNormBounds]:
    bounds = []
    for i in range(len(prob.services)):
        lat_vals, hop_vals = [], []
        for j in prob.candidate_nodes:
            t_proc, t_comm = _calc_times(i, j, prob)
            lat_vals.append(t_proc + t_comm)
            hop_vals.append(float(_get_hops(i, j, prob)))
        bounds.append(ServiceNormBounds(lat_min=min(lat_vals), lat_max=max(lat_vals),
                                        hop_min=min(hop_vals), hop_max=max(hop_vals)))
    return bounds


def _calc_times(i: int, node: int, prob: PlacementProblem) -> Tuple[float, float]:
    """Processing and communication time (seconds): per-hop store-and-forward transmission
    of request and response, plus round-trip propagation, between the requester and `node`."""
    t_proc_ms = prob.service_inst[i] / max(prob.node_ipt[node], 1e-9)
    src = prob.service_source[i]
    t_comm_ms = (prob.service_input_bytes[i] / prob.path_bw_bytes_per_ms[src][node]
                 + prob.service_output_bytes[i] / prob.path_bw_bytes_per_ms[node][src])
    t_comm_ms += prob.path_propagation_ms[src][node] + prob.path_propagation_ms[node][src]
    return t_proc_ms / 1000.0, t_comm_ms / 1000.0


def _get_hops(i: int, node: int, prob: PlacementProblem) -> int:
    return prob.hop_dist[prob.service_source[i]][node]


def _node_headroom(node: int, prob: PlacementProblem, ram_load: float, cpu_load: float) -> float:
    """1 - the worse of post-placement RAM/CPU utilization, in [0, 1]. Cloud is unbounded (1.0)."""
    if node == prob.cloud_id:
        return 1.0
    ram_cap, cpu_cap = prob.node_ram[node], prob.node_ipt[node]
    return 1.0 - max(ram_load / ram_cap if ram_cap > 0 else 0.0, cpu_load / cpu_cap if cpu_cap > 0 else 0.0)


def _minmax(val: float, lo: float, hi: float) -> float:
    if hi - lo < 1e-12: return 0.0
    return min(1.0, max(0.0, (val - lo) / (hi - lo)))


def _compute_total_cost(chrom: List[int], prob: PlacementProblem, bounds: List[ServiceNormBounds],
                        *, penalise_invalid: bool = True) -> float:
    """Cost to minimize: alpha*latency + beta*hops + gamma*(1 - headroom), per-service min-max
    normalized, plus (if penalise_invalid) the cloud-fallback and deadline penalties."""
    ram_load: Dict[int, float] = {}
    cpu_load: Dict[int, float] = {}
    for i, node in enumerate(chrom):
        if node != prob.cloud_id:
            ram_load[node] = ram_load.get(node, 0.0) + prob.service_ram[i]
            cpu_load[node] = cpu_load.get(node, 0.0) + prob.service_cpu[i]

    cost = 0.0
    for i, node in enumerate(chrom):
        t_proc, t_comm = _calc_times(i, node, prob)
        b = bounds[i]
        headroom = _node_headroom(node, prob, ram_load.get(node, 0.0), cpu_load.get(node, 0.0))
        cost += (prob.alpha * _minmax(t_proc + t_comm, b.lat_min, b.lat_max)
                 + prob.beta * _minmax(_get_hops(i, node, prob), b.hop_min, b.hop_max)
                 + prob.gamma * (1.0 - headroom))

    if penalise_invalid:
        fog = [i for i, node in enumerate(chrom) if node != prob.cloud_id]
        cloud_penalty = cloud_coefficient(prob, sum(prob.service_ram[i] for i in fog), sum(prob.service_cpu[i] for i in fog))
        for i, node in enumerate(chrom):
            if node == prob.cloud_id:
                cost += cloud_penalty
        for i, node in enumerate(chrom):
            deadline = prob.service_deadline[i]
            t_proc, t_comm = _calc_times(i, node, prob)
            if t_proc + t_comm > deadline and deadline > 0:
                cost += PENALTY_WEIGHT * (((t_proc + t_comm) - deadline) / deadline)
    return cost


def evaluate_ram_valid(chrom: List[int], prob: PlacementProblem) -> bool:
    node_load: Dict[int, float] = {}
    for i, node in enumerate(chrom):
        if node != prob.cloud_id:
            node_load[node] = node_load.get(node, 0.0) + prob.service_ram[i]
    return all(load <= prob.node_ram[n] for n, load in node_load.items())


def evaluate_cpu_valid(chrom: List[int], prob: PlacementProblem) -> bool:
    node_load: Dict[int, float] = {}
    for i, node in enumerate(chrom):
        if node != prob.cloud_id:
            node_load[node] = node_load.get(node, 0.0) + prob.service_cpu[i]
    return all(load <= prob.node_ipt[n] for n, load in node_load.items())


# ---------------------------------------------------------------------------
# Chromosome helpers
# ---------------------------------------------------------------------------
def _feasible_first_chrom(prob: PlacementProblem, order, key) -> List[int]:
    """Service by service: among fog nodes (in `order`) with enough residual RAM and CPU, the one
    with the smallest (key(i, node), node); the cloud when none fits."""
    if not prob.services or not prob.fog_nodes: return []
    left_ram = {n: prob.node_ram[n] for n in prob.fog_nodes}
    left_cpu = {n: prob.node_ipt[n] for n in prob.fog_nodes}
    chrom: List[int] = []
    for i in range(len(prob.services)):
        fits = [n for n in order if left_ram[n] >= prob.service_ram[i] and left_cpu[n] >= prob.service_cpu[i]]
        chosen = min(fits, key=lambda n: (key(i, n), n)) if fits else prob.cloud_id
        if fits:
            left_ram[chosen] -= prob.service_ram[i]
            left_cpu[chosen] -= prob.service_cpu[i]
        chrom.append(chosen)
    return chrom


def greedy_seed_chrom(prob: PlacementProblem) -> List[int]:
    """Capacity baseline / seed: first fog node by descending IPT that fits [Pakpahan et al., 2025]."""
    if INITIALIZATION == 'random':
        return repair_chromosome(random_chrom(prob), prob, precompute_normalization_bounds(prob))
    ranked = sorted(prob.fog_nodes, key=lambda n: prob.node_ipt[n], reverse=True)
    rank = {n: r for r, n in enumerate(ranked)}
    return _feasible_first_chrom(prob, ranked, lambda i, n: rank[n])


def nearest_feasible_chrom(prob: PlacementProblem) -> List[int]:
    """Baseline: fewest hops from the service's source, ties by estimated latency."""
    return _feasible_first_chrom(prob, prob.fog_nodes, lambda i, n: (_get_hops(i, n, prob), sum(_calc_times(i, n, prob))))


def min_latency_chrom(prob: PlacementProblem) -> List[int]:
    """Baseline: lowest estimated latency (t_proc + t_comm), ties by hops."""
    return _feasible_first_chrom(prob, prob.fog_nodes, lambda i, n: (sum(_calc_times(i, n, prob)), _get_hops(i, n, prob)))


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


def _find_cloud_id(entities) -> int:
    clouds = [eid for eid, e in entities.items() if e["type"] == "CLOUD"]
    if len(clouds) != 1:
        raise ValueError(f'Topology must have exactly one CLOUD node, found {len(clouds)}')
    return clouds[0]


def _source_node(app_id: str, message_name: str, users) -> int:
    for src in users["sources"]:
        if src["app"] == app_id and src["message"] == message_name:
            return src["id_resource"]
    raise ValueError(f'No user source for app {app_id}, message {message_name}')


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
    ram = sum(prob.service_ram[i] for i in fog)
    cpu = sum(prob.service_cpu[i] for i in fog)
    ram_cap = sum(prob.node_ram[n] for n in prob.fog_nodes)
    cpu_cap = sum(prob.node_ipt[n] for n in prob.fog_nodes)
    return dict(cloud_mode=CLOUD_MODE, cloud_coefficient=cloud_coefficient(prob, ram, cpu),
                ram_pressure=ram / ram_cap if ram_cap else None, cpu_pressure=cpu / cpu_cap if cpu_cap else None,
                fog_ram_reserved=ram, fog_ram_capacity=ram_cap, fog_cpu_reserved=cpu, fog_cpu_capacity=cpu_cap,
                services=len(chrom), cloud_services=len(chrom) - len(fog))


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
