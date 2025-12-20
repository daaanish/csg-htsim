#!/usr/bin/env python3
"""
Convert HARP CSV traffic matrices to htsim .tm format using Quantized Rate Aggregation.

CSV format expected:
    tm_id,src,dst,demand_mbps

TM format produced:
    Nodes <N>
    Connections <C>
    
    <src>-><dst> start 0 size <bytes>
    ...

QUANTIZED RATE AGGREGATION (QRA):
The simulator enforces a single global sending rate for all flows, preventing
direct assignment of unique variable demands (demand_mbps) to different source-
destination pairs. To work around this:

1. We configure the simulator with a small, atomic "base rate" (e.g., 1 Mbps)
2. For each demand, we calculate k = ceil(demand_mbps / base_rate_mbps)
3. We instantiate k parallel micro-flows between the same src-dst pair
4. Each micro-flow sends at base_rate with a fixed flow_size
5. The effective bandwidth = k * base_rate_mbps

This treats bandwidth as a discrete quantity built from identical "blocks".

Example:
    - base_rate = 1 Mbps, flow_size = 1 MB
    - demand_mbps = 8 Mbps for pair (1, 6)
    - Result: 8 parallel flows from 1->6, each sending 1 MB at 1 Mbps
    - Aggregate throughput: ~8 Mbps
"""
import argparse
import csv
import math
import os
import pickle
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np


def csv_to_tm(csv_path: Path, output_path: Path, num_nodes: int = 12,
              base_rate_mbps: float = 1.0, flow_size_bytes: int = 1_000_000,
              scale_factor: float = 1.0, path_indices: Optional[List[int]] = None,
              split_ratios_file: Optional[Path] = None,
              pairs_dict_file: Optional[Path] = None,
              path_mapping_file: Optional[Path] = None):
    """
    Convert a single CSV TM to htsim .tm format using Quantized Rate Aggregation.
    
    Args:
        csv_path: Path to input CSV file
        output_path: Path to output .tm file
        num_nodes: Number of nodes in topology
        base_rate_mbps: The atomic rate each micro-flow sends at (simulator -rate param)
        flow_size_bytes: Size of each micro-flow in bytes
        scale_factor: Scale factor for demand (default 1.0)
        path_indices: Optional list of path indices for all flows (for TE)
        split_ratios_file: Optional path to .npy file with split ratios (shape N_pairs x N_paths)
        pairs_dict_file: Optional path to .pkl file mapping (src,dst) -> path lists
    
    Returns:
        Tuple of (total_flows_generated, od_pair_count)
    """
    # Load split ratios and pairs mapping if provided
    split_ratios_matrix = None
    pairs_to_idx: Dict[Tuple[int, int], int] = {}
    path_mapping: Dict[str, Dict[int, int]] = {}  # "src,dst" -> {gurobi_idx: htsim_idx}
    
    if split_ratios_file and pairs_dict_file:
        if split_ratios_file.exists() and pairs_dict_file.exists():
            # Load split ratios (.npy)
            split_ratios_matrix = np.load(split_ratios_file)
            
            # Load pairs dict (.pkl) and build index mapping
            with open(pairs_dict_file, 'rb') as f:
                pairs_dict = pickle.load(f)
            
            # The pairs dict keys are (src, dst) tuples; build index from sorted keys
            sorted_pairs = sorted(pairs_dict.keys())
            for idx, pair in enumerate(sorted_pairs):
                pairs_to_idx[pair] = idx
    
    # Load path mapping if provided (for translating Gurobi paths to htsim paths)
    if path_mapping_file and path_mapping_file.exists():
        import json
        with open(path_mapping_file, 'r') as f:
            path_mapping = json.load(f)
    
    # Collect demands per OD pair
    od_demands = {}  # (src, dst) -> demand_mbps
    
    with csv_path.open('r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = int(row['src'])
            dst = int(row['dst'])
            
            # Support both demand_mbps and demand_Gbps columns
            if 'demand_mbps' in row:
                demand_mbps = float(row['demand_mbps']) * scale_factor
            elif 'demand_Gbps' in row:
                demand_mbps = float(row['demand_Gbps']) * 1000 * scale_factor
            else:
                raise ValueError("CSV must have 'demand_mbps' or 'demand_Gbps' column")
            
            # Skip self-loops or zero demand
            if src == dst or demand_mbps <= 0:
                continue
            
            od_demands[(src, dst)] = demand_mbps
    
    # Generate micro-flows using Quantized Rate Aggregation
    flows = []  # List of (src, dst, size_bytes, extra_params_str)
    
    for (src, dst), demand_mbps in od_demands.items():
        # Calculate number of parallel micro-flows needed
        k = max(1, math.ceil(demand_mbps / base_rate_mbps))
        
        # Build extra parameters string
        extra_params = []
        
        # Add path_indices if provided (global for all flows)
        if path_indices:
            extra_params.append(f"path_indices {','.join(str(p) for p in path_indices)}")
        
        # Add split ratios if available for this OD pair
        if split_ratios_matrix is not None and (src, dst) in pairs_to_idx:
            pair_idx = pairs_to_idx[(src, dst)]
            if pair_idx < split_ratios_matrix.shape[0]:
                gurobi_ratios = split_ratios_matrix[pair_idx]
                
                # Get Gurobi's paths for this OD pair
                gurobi_paths = pairs_dict.get((src, dst), [])
                
                # Build explicit_routes from Gurobi's paths
                # Format: explicit_routes q_r1_r2|q_r2_r5;q_r1_r2|q_r2_r6|q_r6_r7
                # Only include paths with non-zero split ratios
                explicit_route_strs = []
                used_ratios = []
                
                for path_idx, ratio in enumerate(gurobi_ratios):
                    if ratio > 1e-9 and path_idx < len(gurobi_paths):
                        # Convert path edges to queue names
                        path_edges = gurobi_paths[path_idx]
                        queue_names = []
                        for edge in path_edges:
                            # edge is (src_node, dst_node) with 0-indexed nodes
                            # Convert to queue name: q_r<src+1>_r<dst+1>
                            queue_name = f"q_r{edge[0]+1}_r{edge[1]+1}"
                            queue_names.append(queue_name)
                        if queue_names:
                            explicit_route_strs.append("|".join(queue_names))
                            used_ratios.append(ratio)
                
                if explicit_route_strs:
                    # Normalize ratios
                    total = sum(used_ratios)
                    if total > 0:
                        used_ratios = [r / total for r in used_ratios]
                    
                    # Add explicit_routes parameter
                    extra_params.append(f"explicit_routes {';'.join(explicit_route_strs)}")
                    # Add split ratios for the used paths
                    ratio_strs = [f"{r:.6f}" for r in used_ratios]
                    extra_params.append(f"split {','.join(ratio_strs)}")
        
        extra_str = " " + " ".join(extra_params) if extra_params else ""
        
        # Generate k micro-flows for this OD pair
        for flow_idx in range(k):
            flows.append((src, dst, flow_size_bytes, extra_str))
    
    # Write .tm file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w') as f:
        f.write(f"# Generated from {csv_path.name} using Quantized Rate Aggregation\n")
        f.write(f"# base_rate_mbps={base_rate_mbps}, flow_size_bytes={flow_size_bytes}\n")
        if split_ratios_file:
            f.write(f"# split_ratios_file={split_ratios_file.name}\n")
        f.write(f"Nodes {num_nodes}\n")
        f.write(f"Connections {len(flows)}\n\n")
        
        for src, dst, size, extra in flows:
            f.write(f"{src}->{dst} start 0 size {size}{extra}\n")
    
    return len(flows), len(od_demands)


def convert_batch(csv_dir: Path, output_dir: Path, num_nodes: int = 12,
                  base_rate_mbps: float = 1.0, flow_size_bytes: int = 1_000_000,
                  scale_factor: float = 1.0, tm_ids: list = None, 
                  path_indices: Optional[List[int]] = None,
                  split_ratios_dir: Optional[Path] = None,
                  pairs_dict_file: Optional[Path] = None,
                  path_mapping_file: Optional[Path] = None,
                  verbose: bool = True):
    """
    Convert multiple CSV TMs to .tm format using Quantized Rate Aggregation.
    
    Args:
        csv_dir: Directory containing CSV files
        output_dir: Directory for output .tm files
        num_nodes: Number of nodes in topology
        base_rate_mbps: The atomic rate each micro-flow sends at
        flow_size_bytes: Size of each micro-flow in bytes
        scale_factor: Scale factor for demand
        tm_ids: Optional list of specific TM IDs to convert
        path_indices: Optional list of path indices for all flows
        split_ratios_dir: Optional directory containing split_ratios_snapshot_{tm_id}.npy files
        pairs_dict_file: Optional path to pairs dict .pkl file
        verbose: Print progress
    
    Returns:
        Dict mapping tm_id to (output_path, total_flows, od_pairs)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    csv_files = sorted(csv_dir.glob("tm_*.csv"))
    results = {}
    
    for csv_path in csv_files:
        # Extract TM ID from filename (tm_123.csv -> 123)
        try:
            tm_id = int(csv_path.stem.split('_')[1])
        except (IndexError, ValueError):
            continue
        
        # Filter by tm_ids if specified
        if tm_ids is not None and tm_id not in tm_ids:
            continue
        
        output_path = output_dir / f"tm_{tm_id}.tm"
        
        # Look up split ratios file for this TM if directory provided
        split_ratios_file = None
        if split_ratios_dir:
            split_ratios_file = split_ratios_dir / f"split_ratios_snapshot_{tm_id}.npy"
            if not split_ratios_file.exists():
                split_ratios_file = None
        
        try:
            total_flows, od_pairs = csv_to_tm(
                csv_path, output_path, num_nodes,
                base_rate_mbps, flow_size_bytes, scale_factor, path_indices,
                split_ratios_file=split_ratios_file,
                pairs_dict_file=pairs_dict_file,
                path_mapping_file=path_mapping_file
            )
            results[tm_id] = (output_path, total_flows, od_pairs)
            split_info = " (with optimal splits)" if split_ratios_file else ""
            if verbose:
                print(f"Converted tm_{tm_id}: {od_pairs} OD pairs -> {total_flows} micro-flows{split_info}")
        except Exception as e:
            print(f"Error converting {csv_path}: {e}", file=sys.stderr)
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert HARP CSV traffic matrices to htsim .tm format using Quantized Rate Aggregation"
    )
    parser.add_argument("csv_dir", help="Directory containing CSV TM files")
    parser.add_argument("output_dir", help="Output directory for .tm files")
    parser.add_argument("--nodes", type=int, default=12,
                        help="Number of nodes in topology (default: 12)")
    parser.add_argument("--base-rate", type=float, default=1.0,
                        help="Base rate per micro-flow in Mbps (default: 1.0)")
    parser.add_argument("--flow-size", type=int, default=1_000_000,
                        help="Size of each micro-flow in bytes (default: 1000000)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Scale factor for demand (default: 1.0)")
    parser.add_argument("--tm-ids", type=int, nargs="+",
                        help="Specific TM IDs to convert")
    parser.add_argument("--path-indices", type=int, nargs="+",
                        help="Path indices for all flows (for TE)")
    parser.add_argument("--split-ratios-dir", type=str,
                        help="Directory containing split_ratios_snapshot_{tm_id}.npy files")
    parser.add_argument("--pairs-dict", type=str,
                        help="Path to pairs dict .pkl file (maps OD pairs to indices)")
    parser.add_argument("--path-mapping", type=str,
                        help="Path to JSON file mapping Gurobi path indices to htsim indices")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress output")
    
    args = parser.parse_args()
    
    csv_dir = Path(args.csv_dir)
    output_dir = Path(args.output_dir)
    
    if not csv_dir.is_dir():
        print(f"Error: {csv_dir} is not a directory", file=sys.stderr)
        sys.exit(1)
    
    split_ratios_dir = Path(args.split_ratios_dir) if args.split_ratios_dir else None
    pairs_dict_file = Path(args.pairs_dict) if args.pairs_dict else None
    path_mapping_file = Path(args.path_mapping) if args.path_mapping else None
    
    print(f"Quantized Rate Aggregation:")
    print(f"  base_rate_mbps = {args.base_rate}")
    print(f"  flow_size_bytes = {args.flow_size}")
    print(f"  Effective flow duration = {args.flow_size * 8 / (args.base_rate * 1e6):.3f} sec")
    if split_ratios_dir:
        print(f"  split_ratios_dir = {split_ratios_dir}")
    if pairs_dict_file:
        print(f"  pairs_dict = {pairs_dict_file}")
    if path_mapping_file:
        print(f"  path_mapping = {path_mapping_file}")
    print()
    
    results = convert_batch(
        csv_dir, output_dir, 
        num_nodes=args.nodes,
        base_rate_mbps=args.base_rate,
        flow_size_bytes=args.flow_size,
        scale_factor=args.scale,
        tm_ids=args.tm_ids,
        path_indices=args.path_indices,
        split_ratios_dir=split_ratios_dir,
        pairs_dict_file=pairs_dict_file,
        path_mapping_file=path_mapping_file,
        verbose=not args.quiet
    )
    
    total_flows = sum(r[1] for r in results.values())
    total_od_pairs = sum(r[2] for r in results.values())
    print(f"\nConverted {len(results)} traffic matrices to {output_dir}")
    print(f"Total: {total_od_pairs} OD pairs -> {total_flows} micro-flows")


if __name__ == "__main__":
    main()
