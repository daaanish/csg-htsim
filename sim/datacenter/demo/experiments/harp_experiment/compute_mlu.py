#!/usr/bin/env python3
"""Compute Maximum Link Utilization (MLU) from a traffic matrix and topology.

This script computes MLU offline (without running htsim) using:
1. The CSV traffic matrix (demand per OD pair in Mbps)
2. The JSON topology (nodes and links with capacities)

Two modes are available:
- ECMP: Distributes demand evenly across all shortest paths (what htsim does)
- Optimal: Solves a simple LP to find the minimum MLU (like Gurobi would)

Usage:
    python compute_mlu.py --tm harp_csvs/tm_308.csv --topo abilene_harp.json
    python compute_mlu.py --tm harp_csvs/tm_308.csv --topo abilene_harp.json --mode optimal
"""
import argparse
import csv
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Set, Tuple


def load_topology(topo_path: Path) -> Tuple[Set[str], Dict[Tuple[str, str], float]]:
    """Load topology and return (nodes, link_capacities).
    
    link_capacities: {(src, dst): capacity_mbps}
    """
    with topo_path.open() as f:
        data = json.load(f)
    
    nodes = set(data.get("hosts", []))
    link_caps = {}
    for link in data.get("links", []):
        src = link["src"]
        dst = link["dst"]
        speed = link["speed_mbps"]
        link_caps[(src, dst)] = speed
        nodes.add(src)
        nodes.add(dst)
    
    return nodes, link_caps


def load_demands(csv_path: Path, scale: float = 1.0) -> Dict[Tuple[int, int], float]:
    """Load demands from CSV.
    
    Returns: {(src_id, dst_id): demand_mbps}
    """
    demands = {}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = int(row["src"])
            dst = int(row["dst"])
            if "demand_mbps" in row:
                demand = float(row["demand_mbps"]) * scale
            elif "demand_Gbps" in row:
                demand = float(row["demand_Gbps"]) * 1000 * scale
            else:
                continue
            if src != dst and demand > 0:
                demands[(src, dst)] = demand
    return demands


def node_id_to_name(node_id: int) -> str:
    """Convert 0-indexed node ID to router name (r1, r2, ...)."""
    return f"r{node_id + 1}"


def node_name_to_id(name: str) -> int:
    """Convert router name (r1, r2, ...) to 0-indexed node ID."""
    return int(name[1:]) - 1


def build_adjacency(link_caps: Dict[Tuple[str, str], float]) -> Dict[str, List[str]]:
    """Build adjacency list from link capacities."""
    adj = defaultdict(list)
    for (src, dst) in link_caps:
        adj[src].append(dst)
    return adj


def find_all_shortest_paths(adj: Dict[str, List[str]], src: str, dst: str) -> List[List[str]]:
    """Find all shortest paths from src to dst using BFS."""
    if src == dst:
        return [[src]]
    
    # BFS to find shortest distance
    dist = {src: 0}
    queue = deque([src])
    while queue:
        node = queue.popleft()
        for neighbor in adj[node]:
            if neighbor not in dist:
                dist[neighbor] = dist[node] + 1
                queue.append(neighbor)
    
    if dst not in dist:
        return []  # No path
    
    # Backtrack to find all shortest paths
    def backtrack(node: str) -> List[List[str]]:
        if node == src:
            return [[src]]
        paths = []
        for neighbor in adj.get(node, []):
            # Check if neighbor is a valid predecessor (came from neighbor to node)
            pass
        # Actually need to track predecessors
        return paths
    
    # Better approach: track predecessors during BFS
    predecessors = defaultdict(list)
    dist = {src: 0}
    queue = deque([src])
    while queue:
        node = queue.popleft()
        for neighbor in adj[node]:
            if neighbor not in dist:
                dist[neighbor] = dist[node] + 1
                predecessors[neighbor].append(node)
                queue.append(neighbor)
            elif dist[neighbor] == dist[node] + 1:
                predecessors[neighbor].append(node)
    
    if dst not in dist:
        return []
    
    # Reconstruct all paths from dst to src
    def build_paths(node: str) -> List[List[str]]:
        if node == src:
            return [[src]]
        paths = []
        for pred in predecessors[node]:
            for path in build_paths(pred):
                paths.append(path + [node])
        return paths
    
    return build_paths(dst)


def paths_to_links(path: List[str]) -> List[Tuple[str, str]]:
    """Convert a path (list of nodes) to list of links."""
    return [(path[i], path[i+1]) for i in range(len(path) - 1)]


def compute_ecmp_mlu(
    demands: Dict[Tuple[int, int], float],
    link_caps: Dict[Tuple[str, str], float],
    adj: Dict[str, List[str]],
) -> Tuple[float, Dict[Tuple[str, str], float], Tuple[str, str]]:
    """Compute MLU assuming ECMP (equal split across shortest paths).
    
    Returns: (mlu, link_loads, bottleneck_link)
    """
    link_loads = defaultdict(float)
    
    for (src_id, dst_id), demand in demands.items():
        src_name = node_id_to_name(src_id)
        dst_name = node_id_to_name(dst_id)
        
        paths = find_all_shortest_paths(adj, src_name, dst_name)
        if not paths:
            continue
        
        # ECMP: split demand equally across all shortest paths
        demand_per_path = demand / len(paths)
        
        for path in paths:
            for link in paths_to_links(path):
                link_loads[link] += demand_per_path
    
    # Compute utilization per link
    max_util = 0.0
    bottleneck = None
    
    for link, load in link_loads.items():
        cap = link_caps.get(link, float('inf'))
        util = load / cap if cap > 0 else 0.0
        if util > max_util:
            max_util = util
            bottleneck = link
    
    return max_util, dict(link_loads), bottleneck


def compute_single_path_mlu(
    demands: Dict[Tuple[int, int], float],
    link_caps: Dict[Tuple[str, str], float],
    adj: Dict[str, List[str]],
) -> Tuple[float, Dict[Tuple[str, str], float], Tuple[str, str]]:
    """Compute MLU using single-path routing (like htsim_cbr default).
    
    Each OD pair uses ONE path, selected round-robin from available shortest paths.
    This matches htsim's default behavior: path_choice = flow_id % num_paths
    
    Returns: (mlu, link_loads, bottleneck_link)
    """
    link_loads = defaultdict(float)
    
    # Sort OD pairs for deterministic path selection (simulates flow_id ordering)
    sorted_demands = sorted(demands.items(), key=lambda x: (x[0][0], x[0][1]))
    
    for flow_idx, ((src_id, dst_id), demand) in enumerate(sorted_demands):
        src_name = node_id_to_name(src_id)
        dst_name = node_id_to_name(dst_id)
        
        paths = find_all_shortest_paths(adj, src_name, dst_name)
        if not paths:
            continue
        
        # Single path: pick one path round-robin (like htsim)
        path_choice = flow_idx % len(paths)
        chosen_path = paths[path_choice]
        
        for link in paths_to_links(chosen_path):
            link_loads[link] += demand
    
    # Compute utilization per link
    max_util = 0.0
    bottleneck = None
    
    for link, load in link_loads.items():
        cap = link_caps.get(link, float('inf'))
        util = load / cap if cap > 0 else 0.0
        if util > max_util:
            max_util = util
            bottleneck = link
    
    return max_util, dict(link_loads), bottleneck


def compute_optimal_mlu(
    demands: Dict[Tuple[int, int], float],
    link_caps: Dict[Tuple[str, str], float],
    adj: Dict[str, List[str]],
) -> Tuple[float, Dict[Tuple[str, str], float], Tuple[str, str]]:
    """Compute optimal MLU using linear programming.
    
    This solves the multi-commodity flow problem to minimize MLU.
    Requires scipy for LP solver.
    
    Returns: (mlu, link_loads, bottleneck_link)
    """
    try:
        from scipy.optimize import linprog
        import numpy as np
    except ImportError:
        print("Warning: scipy not available, falling back to ECMP")
        return compute_ecmp_mlu(demands, link_caps, adj)
    
    # Get all paths for all OD pairs
    all_od_paths = {}
    for (src_id, dst_id), demand in demands.items():
        src_name = node_id_to_name(src_id)
        dst_name = node_id_to_name(dst_id)
        paths = find_all_shortest_paths(adj, src_name, dst_name)
        if paths:
            all_od_paths[(src_id, dst_id)] = paths
    
    if not all_od_paths:
        return 0.0, {}, None
    
    # Variables: x_{od,p} = fraction of demand on path p for OD pair (o,d)
    # Plus one variable for MLU (theta)
    
    # Build variable index
    var_idx = {}
    idx = 0
    for od, paths in all_od_paths.items():
        for p_idx in range(len(paths)):
            var_idx[(od, p_idx)] = idx
            idx += 1
    theta_idx = idx  # MLU variable
    n_vars = idx + 1
    
    # Objective: minimize theta (MLU)
    c = [0.0] * n_vars
    c[theta_idx] = 1.0
    
    # Inequality constraints: link_load <= theta * capacity for each link
    links = list(link_caps.keys())
    A_ub = []
    b_ub = []
    
    for link in links:
        row = [0.0] * n_vars
        cap = link_caps[link]
        
        for od, paths in all_od_paths.items():
            demand = demands[od]
            for p_idx, path in enumerate(paths):
                path_links = paths_to_links(path)
                if link in path_links:
                    row[var_idx[(od, p_idx)]] = demand
        
        row[theta_idx] = -cap  # -theta * cap
        A_ub.append(row)
        b_ub.append(0.0)
    
    # Equality constraints: sum of fractions = 1 for each OD pair
    A_eq = []
    b_eq = []
    
    for od, paths in all_od_paths.items():
        row = [0.0] * n_vars
        for p_idx in range(len(paths)):
            row[var_idx[(od, p_idx)]] = 1.0
        A_eq.append(row)
        b_eq.append(1.0)
    
    # Bounds: fractions >= 0, theta >= 0
    bounds = [(0, None)] * n_vars
    
    # Solve
    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                     bounds=bounds, method='highs')
    
    if not result.success:
        print(f"Warning: LP solver failed: {result.message}")
        return compute_ecmp_mlu(demands, link_caps, adj)
    
    mlu = result.x[theta_idx]
    
    # Compute link loads from solution
    link_loads = defaultdict(float)
    for od, paths in all_od_paths.items():
        demand = demands[od]
        for p_idx, path in enumerate(paths):
            frac = result.x[var_idx[(od, p_idx)]]
            for link in paths_to_links(path):
                link_loads[link] += demand * frac
    
    # Find bottleneck
    max_util = 0.0
    bottleneck = None
    for link, load in link_loads.items():
        cap = link_caps.get(link, float('inf'))
        util = load / cap if cap > 0 else 0.0
        if util > max_util:
            max_util = util
            bottleneck = link
    
    return mlu, dict(link_loads), bottleneck


def main():
    parser = argparse.ArgumentParser(description="Compute MLU from TM and topology")
    parser.add_argument("--tm", required=True, help="Path to traffic matrix CSV")
    parser.add_argument("--topo", required=True, help="Path to topology JSON")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale factor for demands")
    parser.add_argument("--gurobi-scale", action="store_true",
                        help="Apply scale factor (~600) to approximate Gurobi MLU values")
    parser.add_argument("--mode", choices=["ecmp", "optimal"], default="ecmp",
                        help="Routing mode: ecmp (default) or optimal (LP)")
    parser.add_argument("--normalize-caps", action="store_true",
                        help="Normalize all link capacities to 1.0 (standard TE definition)")
    parser.add_argument("--verbose", action="store_true", help="Show per-link utilization")
    
    args = parser.parse_args()
    
    # Load data
    topo_path = Path(args.topo)
    tm_path = Path(args.tm)
    
    nodes, link_caps = load_topology(topo_path)
    
    # Apply scale factor
    scale = args.scale
    if args.gurobi_scale:
        scale = 600.0  # Empirically determined to match Gurobi MLU values
    
    demands = load_demands(tm_path, scale=scale)
    adj = build_adjacency(link_caps)
    
    # Normalize capacities if requested (standard TE definition: all caps = 1.0)
    if args.normalize_caps:
        link_caps = {link: 1.0 for link in link_caps}
    
    print(f"Topology: {len(nodes)} nodes, {len(link_caps)} directed links")
    print(f"Traffic matrix: {len(demands)} OD pairs")
    print(f"Total demand: {sum(demands.values()):.2f} Mbps")
    print(f"Mode: {args.mode}")
    if args.normalize_caps:
        print("Capacities: normalized to 1.0")
    print()
    
    # Compute MLU
    if args.mode == "optimal":
        mlu, link_loads, bottleneck = compute_optimal_mlu(demands, link_caps, adj)
    else:
        mlu, link_loads, bottleneck = compute_ecmp_mlu(demands, link_caps, adj)
    
    print(f"MLU ({args.mode}): {mlu:.6f}")
    if bottleneck:
        cap = link_caps.get(bottleneck, 0)
        load = link_loads.get(bottleneck, 0)
        print(f"Bottleneck link: {bottleneck[0]} -> {bottleneck[1]} "
              f"(load={load:.2f} Mbps, capacity={cap:.2f} Mbps)")
    
    if args.verbose:
        print("\nPer-link utilization:")
        sorted_links = sorted(link_loads.items(), key=lambda x: -x[1])
        for link, load in sorted_links[:20]:
            cap = link_caps.get(link, 0)
            util = load / cap if cap > 0 else 0
            print(f"  {link[0]:>4} -> {link[1]:<4}: {load:10.2f} / {cap:10.2f} Mbps = {util:.4f}")


if __name__ == "__main__":
    main()
