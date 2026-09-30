"""
Custom YAFS routing strategies for this repository.

Signature get_path sesuai YAFS DeviceSpeedAwareRouting:
    get_path(self, sim, app_name, message,
             topology_src, alloc_DES, alloc_module, traffic, from_des)

- topology_src : int  — node ID pengirim pesan
- alloc_DES    : dict — {DES_id: node_id}
- alloc_module : dict — {app_name: {service_name: [DES_id, ...]}}
- traffic      : object — YAFS traffic manager (tidak dipakai di sini)
- from_des     : int  — DES ID pengirim (tidak dipakai di sini)
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Tuple

import networkx as nx
from yafs.selection import Selection
from yafs.path_routing import DeviceSpeedAwareRouting as YAFSHopSpeedAwareRouting


# ==========================================================================
# COMM-LATENCY ROUTING — Selaras dengan model T_comm di _common.py
# ==========================================================================

class CommLatencyRouting(Selection):
    """
    Routing yang meminimalkan T_comm persis seperti yang dihitung placement
    optimizer di _common.py:

        T_comm(u→v) = bytes_in/BW_up + bytes_out/BW_down + PR*hops/1000

    Karena bytes per message konstan untuk semua candidate path, bobot
    edge disederhanakan menjadi:

        weight(u→v) = 1/BW(u,v) + PR(u,v)   [ms]

    Di antara beberapa DES instance yang sama-sama reachable, dipilih
    yang total T_comm-nya terpendek — tie-break dengan round-robin
    (identik dengan perilaku DeviceSpeedAwareRouting).

    Parameters
    ----------
    bw_attr    : nama atribut BW di edge topology YAFS  (default ``"BW"``)
    pr_attr    : nama atribut PR di edge topology YAFS  (default ``"PR"``)
    default_bw : fallback BW (bytes/ms) — selaras DEFAULT_LINK_BW di _common.py
    default_pr : fallback PR (ms)       — selaras mean_pr_ms di _common.py
    """

    def __init__(
        self,
        bw_attr: str = "BW",
        pr_attr: str = "PR",
        default_bw: float = 75000.0,
        default_pr: float = 10.0,
    ):
        super().__init__()
        self.bw_attr = bw_attr
        self.pr_attr = pr_attr
        self.default_bw = default_bw
        self.default_pr = default_pr

        # Round-robin counter per DES (sama seperti DeviceSpeedAwareRouting)
        self.counter: Counter = Counter()
        self.controlServices: Dict[Tuple, Tuple] = {}

        # Static-topology caches
        self._weighted_graph: Optional[nx.DiGraph] = None
        self._dist_cache: Dict[Tuple, float] = {}   # (src, dst_node) -> cost
        self._path_cache: Dict[Tuple, List] = {}    # (src, dst_node) -> path

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_weighted_graph(self, topology) -> nx.DiGraph:
        """Bangun graph berbobot T_comm. Dipanggil sekali lalu di-cache."""
        if self._weighted_graph is not None:
            return self._weighted_graph

        G = topology.G
        W = nx.DiGraph()
        W.add_nodes_from(G.nodes(data=True))

        for u, v, ed in G.edges(data=True):
            bw = float(ed.get(self.bw_attr, self.default_bw))
            pr = float(ed.get(self.pr_attr, self.default_pr))
            bw = max(bw, 1e-9)
            W.add_edge(u, v, weight=(1.0 / bw) + pr)

        self._weighted_graph = W
        return W

    def _shortest_path(self, topology, src: int, dst: int):
        """Return (path_list, cost) dari cache atau hitung baru."""
        key = (src, dst)
        if key in self._path_cache:
            return self._path_cache[key], self._dist_cache[key]

        W = self._build_weighted_graph(topology)
        try:
            path = nx.shortest_path(W, source=src, target=dst, weight="weight")
            cost = nx.shortest_path_length(W, source=src, target=dst, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            path, cost = [], float("inf")

        self._path_cache[key] = path
        self._dist_cache[key] = cost
        return path, cost

    # ------------------------------------------------------------------
    # Best DES selection — identik dengan DeviceSpeedAwareRouting
    # tapi menggunakan T_comm cost bukan hop count
    # ------------------------------------------------------------------

    def _compute_best_des(self, node_src, alloc_DES, sim, DES_dst, message):
        """
        Pilih DES instance dengan T_comm terpendek dari node_src.
        Tie-break: round-robin (sama dengan YAFS default).
        """
        best_cost = float("inf")
        best_path = []
        best_des = None
        candidates_same_cost = []

        for des_id in DES_dst:
            node_dst = alloc_DES[des_id]
            path, cost = self._shortest_path(sim.topology, node_src, node_dst)

            if cost < best_cost:
                best_cost = cost
                best_path = path
                best_des = des_id
                candidates_same_cost = []
            elif cost == best_cost:
                if not candidates_same_cost and best_des is not None:
                    candidates_same_cost.append(best_des)
                candidates_same_cost.append(des_id)

        # Tie-break: round-robin
        if candidates_same_cost:
            best_index = 0
            min_count = float("inf")
            for idx, des_id in enumerate(candidates_same_cost):
                if des_id not in self.counter:
                    return best_path, des_id
                if self.counter[des_id] < min_count:
                    min_count = self.counter[des_id]
                    best_index = idx
            return best_path, candidates_same_cost[best_index]

        return best_path, best_des

    # ------------------------------------------------------------------
    # YAFS Selection interface — signature harus PERSIS seperti ini
    # ------------------------------------------------------------------

    def get_path(self, sim, app_name, message,
                 topology_src, alloc_DES, alloc_module, traffic, from_des):
        """
        Dipanggil oleh YAFS engine untuk setiap pesan yang dikirim.
        Return: ([path], [des_id]) atau ([], None) jika tidak ada path.
        """
        node_src = topology_src
        service  = message.dst
        DES_dst  = alloc_module[app_name][service]

        path, des = self._compute_best_des(node_src, alloc_DES, sim, DES_dst, message)

        try:
            des_id = int(des)
            self.counter[des_id] += 1
            self.controlServices[(node_src, service)] = (path, des)
        except (TypeError, ValueError):
            return [], None

        return [path], [des]

    def get_path_from_failure(self, sim, message, link,
                              alloc_DES, alloc_module, traffic, ctime, from_des):
        """Re-route setelah link failure — identik dengan YAFS default."""
        idx = message.path.index(link[0])
        if idx == len(message.path):
            return [], []

        node_src = message.path[idx]
        path, des = self.get_path(
            sim, message.app_name, message,
            node_src, alloc_DES, alloc_module, traffic, from_des,
        )
        if path and len(path[0]) > 0:
            conc_path = (
                message.path[: message.path.index(path[0][0])] + path[0]
            )
            message.dst_int = node_src
            return [conc_path], des
        return [], []

    def clear_routing_cache(self):
        self.counter = Counter()
        self.controlServices = {}
        # Graph cache dipertahankan karena topology statis


# ==========================================================================
# QoS-AWARE ROUTING — Composite latency + energy + cost
# ==========================================================================

class QoSAwareRouting(Selection):
    """
    Routing yang meminimalkan composite cost: latency + energy + cost node.

    Bobot edge:
        latency  = PR_uv + 1/BW_uv
        energy   = atribut 'energy' node dst, atau fallback IPT * energy_per_ipt
        cost     = atribut 'cost' node dst, atau fallback IPT * cost_per_ipt * type_factor

        weight = w_L*norm(latency) + w_E*norm(energy) + w_C*norm(cost)

    Normalisation min-max dilakukan sekali saat graph dibangun.

    Parameters
    ----------
    w_latency, w_energy, w_cost : float — harus jumlah = 1.0
    energy_per_ipt : float — koefisien fallback energy
    cost_per_ipt   : float — koefisien fallback cost
    """

    _TYPE_COST_FACTOR: Dict[str, float] = {
        "CLOUD": 0.8, "FOG": 1.0, "EDGE": 1.2,
    }

    def __init__(
        self,
        w_latency: float = 0.4,
        w_energy: float = 0.3,
        w_cost: float = 0.3,
        energy_per_ipt: float = 0.5,
        cost_per_ipt: float = 1.0,
    ):
        super().__init__()
        total = w_latency + w_energy + w_cost
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.4f} "
                f"(w_latency={w_latency}, w_energy={w_energy}, w_cost={w_cost})"
            )
        self.w_latency = w_latency
        self.w_energy  = w_energy
        self.w_cost    = w_cost
        self.energy_per_ipt = energy_per_ipt
        self.cost_per_ipt   = cost_per_ipt

        self.counter: Counter = Counter()
        self.controlServices: Dict[Tuple, Tuple] = {}

        self._weighted_graph: Optional[nx.DiGraph] = None
        self._dist_cache: Dict[Tuple, float] = {}
        self._path_cache: Dict[Tuple, List] = {}

    def _node_energy(self, nd: dict) -> float:
        if "energy" in nd:
            return float(nd["energy"])
        return float(nd.get("IPT", 1.0)) * self.energy_per_ipt

    def _node_cost(self, nd: dict) -> float:
        if "cost" in nd:
            return float(nd["cost"])
        ipt    = float(nd.get("IPT", 1.0))
        ntype  = str(nd.get("type", "FOG")).upper()
        factor = self._TYPE_COST_FACTOR.get(ntype, 1.0)
        return ipt * self.cost_per_ipt * factor

    def _build_weighted_graph(self, topology) -> nx.DiGraph:
        if self._weighted_graph is not None:
            return self._weighted_graph

        G = topology.G

        # Pass 1: normalisasi constants
        max_lat = max_eng = max_cst = 0.0
        for u, v, ed in G.edges(data=True):
            bw  = float(ed.get("BW", 1.0))
            pr  = float(ed.get("PR", 1.0))
            lat = pr + (1.0 / bw if bw > 0 else 1e6)
            max_lat = max(max_lat, lat)
        for _, nd in G.nodes(data=True):
            max_eng = max(max_eng, self._node_energy(nd))
            max_cst = max(max_cst, self._node_cost(nd))

        max_lat = max(max_lat, 1e-10)
        max_eng = max(max_eng, 1e-10)
        max_cst = max(max_cst, 1e-10)

        # Pass 2: assign bobot
        W = nx.DiGraph()
        W.add_nodes_from(G.nodes(data=True))
        for u, v, ed in G.edges(data=True):
            bw  = float(ed.get("BW", 1.0))
            pr  = float(ed.get("PR", 1.0))
            lat = pr + (1.0 / bw if bw > 0 else 1e6)
            nd_v = G.nodes[v]
            weight = (
                self.w_latency * (lat / max_lat)
                + self.w_energy * (self._node_energy(nd_v) / max_eng)
                + self.w_cost   * (self._node_cost(nd_v)   / max_cst)
            )
            W.add_edge(u, v, weight=weight)

        self._weighted_graph = W
        return W

    def _shortest_path(self, topology, src: int, dst: int):
        key = (src, dst)
        if key in self._path_cache:
            return self._path_cache[key], self._dist_cache[key]

        W = self._build_weighted_graph(topology)
        try:
            path = nx.shortest_path(W, source=src, target=dst, weight="weight")
            cost = nx.shortest_path_length(W, source=src, target=dst, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            path, cost = [], float("inf")

        self._path_cache[key] = path
        self._dist_cache[key] = cost
        return path, cost

    def _compute_best_des(self, node_src, alloc_DES, sim, DES_dst, message):
        best_cost = float("inf")
        best_path = []
        best_des  = None
        candidates = []

        for des_id in DES_dst:
            node_dst = alloc_DES[des_id]
            path, cost = self._shortest_path(sim.topology, node_src, node_dst)
            if cost < best_cost:
                best_cost = cost
                best_path = path
                best_des  = des_id
                candidates = []
            elif cost == best_cost:
                if not candidates and best_des is not None:
                    candidates.append(best_des)
                candidates.append(des_id)

        if candidates:
            best_index, min_count = 0, float("inf")
            for idx, des_id in enumerate(candidates):
                if des_id not in self.counter:
                    return best_path, des_id
                if self.counter[des_id] < min_count:
                    min_count = self.counter[des_id]
                    best_index = idx
            return best_path, candidates[best_index]

        return best_path, best_des

    # YAFS interface — signature identik dengan DeviceSpeedAwareRouting
    def get_path(self, sim, app_name, message,
                 topology_src, alloc_DES, alloc_module, traffic, from_des):
        node_src = topology_src
        service  = message.dst
        DES_dst  = alloc_module[app_name][service]

        path, des = self._compute_best_des(node_src, alloc_DES, sim, DES_dst, message)

        try:
            des_id = int(des)
            self.counter[des_id] += 1
            self.controlServices[(node_src, service)] = (path, des)
        except (TypeError, ValueError):
            return [], None

        return [path], [des]

    def get_path_from_failure(self, sim, message, link,
                              alloc_DES, alloc_module, traffic, ctime, from_des):
        idx = message.path.index(link[0])
        if idx == len(message.path):
            return [], []

        node_src = message.path[idx]
        path, des = self.get_path(
            sim, message.app_name, message,
            node_src, alloc_DES, alloc_module, traffic, from_des,
        )
        if path and len(path[0]) > 0:
            conc_path = (
                message.path[: message.path.index(path[0][0])] + path[0]
            )
            message.dst_int = node_src
            return [conc_path], des
        return [], []

    def clear_routing_cache(self):
        self.counter = Counter()
        self.controlServices = {}


# ==========================================================================
# Factory
# ==========================================================================

def create_routing_strategy(name: str, **kwargs):
    """
    Instantiate a routing strategy by name.

    Parameters
    ----------
    name : str
        - ``"hop_aware"``    — YAFS default, hop count terpendek.
        - ``"comm_latency"`` — T_comm terpendek (1/BW + PR per hop).
                               Selaras dengan model _common.py. REKOMENDASI.
        - ``"qos_aware"``    — Composite latency+energy+cost.
    **kwargs
        Diteruskan ke constructor class yang dipilih.
    """
    normalized = name.lower().replace("-", "_")
    mapping = {
        "hop_aware":    YAFSHopSpeedAwareRouting,
        "comm_latency": CommLatencyRouting,
        "qos_aware":    QoSAwareRouting,
    }

    if normalized not in mapping:
        raise ValueError(
            f"Unknown routing strategy '{name}'. "
            f"Valid options: {sorted(mapping)}"
        )

    import inspect
    cls = mapping[normalized]
    try:
        sig = inspect.signature(cls.__init__)
        valid_params = set(sig.parameters) - {"self"}
        filtered = {k: v for k, v in kwargs.items() if k in valid_params}
        return cls(**filtered)
    except Exception:
        return cls()