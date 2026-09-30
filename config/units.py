"""Explicit adapter to unchanged YAFS: one simulation time unit = one ms.

Canonical scenario BW is bytes/ms. YAFS evaluates bytes/(BW_parameter*1e6).
The engine parameter is therefore canonical BW/1e6, NOT a claimed Mbps unit.
"""
import copy
import math
import networkx as nx


def engine_topology(canonical):
    if canonical.get('_yafs_adapter'):
        raise ValueError('Topology has already been converted for YAFS')
    result=copy.deepcopy(canonical)
    for link in result['link']:
        if not math.isfinite(link['BW']) or link['BW']<=0 or not math.isfinite(link['PR']) or link['PR']<0:
            raise ValueError('Invalid BW or propagation delay')
        link['BW'] /= 1_000_000.0
    for node in result['entity']:
        if not math.isfinite(node['IPT']) or node['IPT']<=0:
            raise ValueError('IPT must be positive and finite')
    result['_yafs_adapter']='canonical bytes/ms to YAFS parameter; clock ms'
    return result


def physical_graph(topology):
    """Edge insertion order matches Topology.load / native hop routing exactly."""
    if topology.get('_yafs_adapter'):
        raise ValueError('Optimizer needs canonical, not engine-adapted topology')
    graph=nx.Graph()
    for edge in topology['link']:
        graph.add_edge(edge['s'],edge['d'],BW=float(edge['BW']),PR=float(edge['PR']))
    if set(graph)!=set(n['id'] for n in topology['entity']) or not nx.is_connected(graph):
        raise ValueError('Benchmark requires a connected static topology')
    return graph
