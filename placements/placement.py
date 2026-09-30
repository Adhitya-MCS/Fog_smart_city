"""
Base class for placement algorithms.
Shared helpers used by all heuristic algorithms — Pakpahan et al. (2025).
"""
from abc import ABC, abstractmethod
from collections import deque


class Placement(ABC):
    def __init__(self):
        self.name = "Placement"

    @abstractmethod
    def generate_allocation(self, topology, applications, users):
        """Generate allocation: returns list of {module_name, app, id_resource}."""
        pass

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _find_cloud_id(self, entities):
        """Return cloud node ID."""
        for eid, edata in entities.items():
            if edata.get("type") == "CLOUD" or edata.get("model") == "cloud":
                return eid
        return max(entities.keys(), default=0)

    def _build_adjacency_map(self, topology):
        """Algorithm 5: direct-neighbor (1-hop) adjacency dict."""
        adj = {}
        for link in topology["link"]:
            s, d = link["s"], link["d"]
            adj.setdefault(s, []).append(d)
            adj.setdefault(d, []).append(s)
        return adj

    def _get_module_chain(self, app):
        """Return module names in chain order (gateway side → last module)."""
        next_mod = {}
        first = None
        for msg in app.get("message", []):
            if msg.get("s") == "None":
                first = msg["d"]
            else:
                next_mod[msg["s"]] = msg["d"]
        if first is None:
            return [m["name"] for m in app.get("module", [])]
        chain = [first]
        while chain[-1] in next_mod:
            chain.append(next_mod[chain[-1]])
        return chain

    def _get_app_source_node(self, app_id, users):
        """Return gateway node for a given app (from users sources)."""
        for src in users.get("sources", []):
            if src["app"] == str(app_id):
                return src["id_resource"]
        return None

    def _bfs_find_node(self, from_node, adj, caps, ram_req, cloud_id):
        """BFS from from_node (inclusive). Return first fog node with enough RAM."""
        visited = set()
        queue = deque([from_node])
        while queue:
            node = queue.popleft()
            if node in visited or node == cloud_id:
                visited.add(node)
                continue
            visited.add(node)
            if caps.get(node, 0) >= ram_req:
                return node
            for nb in adj.get(node, []):
                if nb not in visited:
                    queue.append(nb)
        return None

    def _bfs_find_next_node(self, prev_node, adj, caps, ram_req, cloud_id):
        """BFS from prev_node's neighbors (skip prev_node). Used by Hop2/Hop3."""
        visited = {prev_node}
        queue = deque()
        for nb in adj.get(prev_node, []):
            if nb not in visited and nb != cloud_id:
                queue.append(nb)
                visited.add(nb)
        while queue:
            node = queue.popleft()
            if caps.get(node, 0) >= ram_req:
                return node
            for nb in adj.get(node, []):
                if nb not in visited and nb != cloud_id:
                    queue.append(nb)
                    visited.add(nb)
        return None
