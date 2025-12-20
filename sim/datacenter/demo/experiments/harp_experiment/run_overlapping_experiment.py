#!/usr/bin/env python3
"""
Run continuous overlapping TM experiment.

TMs 1-100 run in a single HTSIM instance with overlapping 5-second intervals.
Tracks per-flow loss and aggregates per-TM metrics.

Usage:
    python run_overlapping_experiment.py --mode default --max-tms 10
    python run_overlapping_experiment.py --mode optimal --max-tms 100
"""

import argparse
import csv
import pickle
import re
import subprocess
import sys
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np

# ============ Configuration ============
TM_INTERVAL_SEC = 5.0             # 5 seconds between TM starts (HARP period)
FLOW_SIZE_BYTES = 100_000_000     # 100MB per flow (same as exp1/exp3)
BASE_RATE_MBPS = 1.0              # 1 Mbps per micro-flow
NUM_NODES = 12


def load_gurobi_data(script_dir: Path) -> Tuple[Dict, Path, Dict[int, float]]:
    """Load Gurobi split ratios and paths."""
    pairs_dict_file = script_dir / "firebolt_dl/abilene_4_paths_dict_cluster_0.pkl"
    split_dir = script_dir / "firebolt_dl/abilene_4_paths"
    mlu_file = script_dir / "firebolt_dl/abilene_4_paths/optimal_values.txt"
    
    with open(pairs_dict_file, 'rb') as f:
        pairs_dict = pickle.load(f)
    
    # Get TM IDs from split ratio files
    sr_files = sorted(split_dir.glob("split_ratios_snapshot_*.npy"))
    tm_ids = [int(f.stem.split('_')[-1]) for f in sr_files]
    
    # Load MLUs
    with open(mlu_file) as f:
        mlus = [float(line.strip()) for line in f if line.strip()]
    
    # Match TM IDs to MLUs
    tm_mlu = dict(zip(tm_ids, mlus[:len(tm_ids)]))
    
    return pairs_dict, split_dir, tm_mlu


def generate_overlapping_tm(
    script_dir: Path,
    output_file: Path,
    use_optimal: bool = False,
    max_tms: int = 100
) -> Tuple[Dict[int, Tuple[int, int]], float, List[int]]:
    """
    Generate combined TM file with overlapping 5-second intervals.
    
    Returns:
        - tm_flow_ranges: Dict[tm_id -> (start_flow_id, end_flow_id)]
        - total_duration: Simulation end time in seconds
        - tm_ids: List of TM IDs included
    """
    pairs_dict, split_dir, tm_mlu = load_gurobi_data(script_dir)
    sorted_pairs = sorted(pairs_dict.keys())
    pairs_to_idx = {p: i for i, p in enumerate(sorted_pairs)}
    
    csv_dir = script_dir / "harp_csvs"
    
    # Get sorted TM IDs (those with Gurobi data)
    tm_ids = sorted(tm_mlu.keys())[:max_tms]
    
    print(f"Generating overlapping TM with {len(tm_ids)} TMs...")
    print(f"  Flow size: {FLOW_SIZE_BYTES/1e6:.0f} MB")
    print(f"  TM interval: {TM_INTERVAL_SEC:.0f} sec")
    print(f"  Mode: {'optimal (explicit_routes)' if use_optimal else 'default routing'}")
    
    all_flows = []
    tm_flow_ranges = {}  # tm_id -> (start_idx, end_idx)
    flow_counter = 0
    processed_tm_count = 0  # Counter for actually processed TMs
    
    for tm_id in tm_ids:
        csv_path = csv_dir / f"tm_{tm_id}.csv"
        if not csv_path.exists():
            continue
        
        start_time_sec = processed_tm_count * TM_INTERVAL_SEC
        start_time_ps = int(start_time_sec * 1e12)
        
        # Load split ratios if using optimal
        split_ratios = None
        if use_optimal:
            sr_file = split_dir / f"split_ratios_snapshot_{tm_id}.npy"
            if sr_file.exists():
                split_ratios = np.load(sr_file)
        
        tm_start_flow = flow_counter
        
        # Read CSV demands
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = int(row['src'])
                dst = int(row['dst'])
                
                if 'demand_mbps' in row:
                    demand_mbps = float(row['demand_mbps'])
                elif 'demand_Gbps' in row:
                    demand_mbps = float(row['demand_Gbps']) * 1000
                else:
                    continue
                
                if src == dst or demand_mbps <= 0:
                    continue
                
                # Number of micro-flows for QRA
                k = max(1, int(np.ceil(demand_mbps / BASE_RATE_MBPS)))
                
                # Build flow parameters
                extra_params = []
                
                if use_optimal and split_ratios is not None and (src, dst) in pairs_to_idx:
                    pair_idx = pairs_to_idx[(src, dst)]
                    if pair_idx < split_ratios.shape[0]:
                        ratios = split_ratios[pair_idx]
                        gurobi_paths = pairs_dict.get((src, dst), [])
                        
                        # Build explicit_routes
                        explicit_route_strs = []
                        used_ratios = []
                        
                        for path_idx, ratio in enumerate(ratios):
                            if ratio > 1e-9 and path_idx < len(gurobi_paths):
                                path_edges = gurobi_paths[path_idx]
                                queue_names = [f"q_r{e[0]+1}_r{e[1]+1}" for e in path_edges]
                                if queue_names:
                                    explicit_route_strs.append("|".join(queue_names))
                                    used_ratios.append(ratio)
                        
                        if explicit_route_strs:
                            total = sum(used_ratios)
                            if total > 0:
                                used_ratios = [r / total for r in used_ratios]
                            extra_params.append(f"explicit_routes {';'.join(explicit_route_strs)}")
                            ratio_strs = [f"{r:.6f}" for r in used_ratios]
                            extra_params.append(f"split {','.join(ratio_strs)}")
                
                extra_str = " " + " ".join(extra_params) if extra_params else ""
                
                # Generate k micro-flows
                for _ in range(k):
                    flow_line = f"{src}->{dst} start {start_time_ps} size {FLOW_SIZE_BYTES}{extra_str}"
                    all_flows.append(flow_line)
                    flow_counter += 1
        
        tm_flow_ranges[tm_id] = (tm_start_flow, flow_counter - 1)
        processed_tm_count += 1
    
    # Calculate simulation end time
    # Last TM starts at (processed_tm_count - 1) * 5s, flows take ~800s to complete
    flow_duration = (FLOW_SIZE_BYTES * 8) / (BASE_RATE_MBPS * 1e6)
    total_duration = (processed_tm_count - 1) * TM_INTERVAL_SEC + flow_duration + 10
    
    # Write combined TM file
    with open(output_file, 'w') as f:
        f.write(f"# Overlapping TM experiment - {'optimal' if use_optimal else 'default'} routing\n")
        f.write(f"# TMs: {len(tm_ids)}, interval: {TM_INTERVAL_SEC}s, flows: {len(all_flows)}\n")
        f.write(f"Nodes {NUM_NODES}\n")
        f.write(f"Connections {len(all_flows)}\n\n")
        for flow in all_flows:
            f.write(flow + "\n")
    
    print(f"Generated: {output_file}")
    print(f"  Total flows: {len(all_flows)}")
    print(f"  Duration: {total_duration:.0f} seconds")
    
    return tm_flow_ranges, total_duration, tm_ids


def run_simulation(
    script_dir: Path,
    tm_file: Path,
    duration_sec: float
) -> Tuple[int, str]:
    """Run htsim_cbr simulation (no .dat log file to save disk space)."""
    htsim = script_dir.parent.parent.parent / "htsim_cbr"
    topo = script_dir / "abilene_harp.json"
    
    # Note: Not using -o to avoid huge log files (14GB+ for 10 TMs)
    # We only need FLOW_STATS from stdout
    cmd = [
        str(htsim),
        "-json_topo", str(topo),
        "-tm", str(tm_file),
        "-rate", str(BASE_RATE_MBPS),
        "-end", str(int(duration_sec)),
    ]
    
    print(f"Running simulation (this may take a while)...")
    print(f"  Simulating {duration_sec:.0f} seconds...")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def parse_flow_stats(stdout_text: str) -> List[Dict]:
    """
    Parse FLOW_STATS lines from htsim output.
    
    Format: FLOW_STATS flow=1 src=1 dst=10 sent_bytes=50000000 received_bytes=50000000
    """
    stats = []
    pat = re.compile(
        r"FLOW_STATS\s+flow=(\d+)\s+src=(\d+)\s+dst=(\d+)\s+"
        r"sent_bytes=(\d+)\s+received_bytes=(\d+)"
    )
    
    for line in stdout_text.splitlines():
        m = pat.search(line)
        if m:
            stats.append({
                "flow_id": int(m.group(1)),
                "src": int(m.group(2)),
                "dst": int(m.group(3)),
                "bytes_sent": int(m.group(4)),
                "bytes_received": int(m.group(5)),
            })
    
    return stats


def aggregate_per_tm_stats(
    flow_stats: List[Dict],
    tm_flow_ranges: Dict[int, Tuple[int, int]],
    tm_mlu: Dict[int, float]
) -> List[Dict]:
    """Aggregate flow stats per TM."""
    results = []
    
    for tm_id, (start_id, end_id) in sorted(tm_flow_ranges.items()):
        # Find flows belonging to this TM
        tm_flows = [f for f in flow_stats if start_id <= f["flow_id"] <= end_id]
        
        if not tm_flows:
            results.append({
                "tm_id": tm_id,
                "gurobi_mlu": tm_mlu.get(tm_id, 0),
                "success": False,
                "error": "No flow stats found"
            })
            continue
        
        total_sent = sum(f["bytes_sent"] for f in tm_flows)
        total_received = sum(f["bytes_received"] for f in tm_flows)
        total_dropped = total_sent - total_received
        
        # Get unique OD pairs
        od_pairs = set((f["src"], f["dst"]) for f in tm_flows)
        
        # Calculate loss rate
        loss_rate = total_dropped / total_sent if total_sent > 0 else 0
        
        # Calculate per-flow max loss
        max_loss = 0
        for f in tm_flows:
            if f["bytes_sent"] > 0:
                flow_loss = (f["bytes_sent"] - f["bytes_received"]) / f["bytes_sent"]
                max_loss = max(max_loss, flow_loss)
        
        results.append({
            "tm_id": tm_id,
            "gurobi_mlu": tm_mlu.get(tm_id, 0),
            "success": True,
            "num_od_pairs": len(od_pairs),
            "num_flows": len(tm_flows),
            "total_bytes_sent": total_sent,
            "total_bytes_received": total_received,
            "total_bytes_dropped": total_dropped,
            "avg_loss_rate": loss_rate,
            "max_loss_rate": max_loss,
        })
    
    return results


def save_results_csv(results: List[Dict], output_path: Path):
    """Save results in same format as exp1/exp3_explicit."""
    with output_path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "tm_id", "gurobi_mlu", "success",
            "num_od_pairs", "num_flows",
            "total_bytes_sent", "total_bytes_received", "total_bytes_dropped",
            "avg_loss_rate", "max_loss_rate", "goodput_ratio", "error"
        ])
        for r in results:
            sent = r.get("total_bytes_sent", 0)
            received = r.get("total_bytes_received", 0)
            goodput_ratio = received / sent if sent > 0 else 0
            
            writer.writerow([
                r.get("tm_id", ""),
                r.get("gurobi_mlu", ""),
                r.get("success", False),
                r.get("num_od_pairs", ""),
                r.get("num_flows", ""),
                r.get("total_bytes_sent", ""),
                r.get("total_bytes_received", ""),
                r.get("total_bytes_dropped", ""),
                r.get("avg_loss_rate", ""),
                r.get("max_loss_rate", ""),
                f"{goodput_ratio:.6f}" if sent > 0 else "",
                r.get("error", ""),
            ])
    print(f"Saved results: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Run overlapping TM experiment")
    parser.add_argument("--mode", choices=["optimal", "default"], required=True,
                        help="Routing mode: optimal (Gurobi) or default (shortest-path)")
    parser.add_argument("--max-tms", type=int, default=10,
                        help="Number of TMs to run (default: 10)")
    parser.add_argument("--end-time", type=float, default=None,
                        help="Override simulation end time (seconds)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory (default: exp4_overlapping_<mode>)")
    parser.add_argument("--generate-only", action="store_true",
                        help="Only generate TM file, don't run simulation")
    args = parser.parse_args()
    
    script_dir = Path(__file__).resolve().parent
    
    use_optimal = (args.mode == "optimal")
    output_dir = Path(args.output_dir) if args.output_dir else script_dir / f"exp4_overlapping_{args.mode}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load MLU data for later
    _, _, tm_mlu = load_gurobi_data(script_dir)
    
    # Generate combined TM
    tm_file = output_dir / f"combined_{args.mode}.tm"
    tm_flow_ranges, duration, tm_ids = generate_overlapping_tm(
        script_dir, tm_file, use_optimal=use_optimal, max_tms=args.max_tms
    )
    
    if args.end_time:
        duration = args.end_time
    
    if args.generate_only:
        print(f"\nTM file generated. To run simulation manually:")
        print(f"  cd {script_dir.parent.parent.parent}")
        print(f"  ./htsim_cbr -json_topo demo/experiments/harp_experiment/abilene_harp.json \\")
        print(f"    -tm {tm_file} -rate 1 -end {int(duration)}")
        return
    
    # Run simulation (no log file - FLOW_STATS from stdout only)
    returncode, output = run_simulation(script_dir, tm_file, duration)
    
    if returncode != 0:
        print(f"Simulation failed with code {returncode}")
        print(output[:2000])
        return
    
    # Parse flow stats from stdout
    flow_stats = parse_flow_stats(output)
    print(f"Parsed {len(flow_stats)} flow stats")
    
    if not flow_stats:
        print("Warning: No FLOW_STATS found in output. Check simulation output.")
        # Print some of the output for debugging
        print("Output sample:")
        print(output[:2000])
        return
    
    # Aggregate per TM
    results = aggregate_per_tm_stats(flow_stats, tm_flow_ranges, tm_mlu)
    
    # Save results
    results_csv = output_dir / "mlu_vs_loss_results.csv"
    save_results_csv(results, results_csv)
    
    # Print summary
    successful = [r for r in results if r["success"]]
    print(f"\n=== Summary ===")
    print(f"Total TMs: {len(results)}")
    print(f"Successful: {len(successful)}")
    
    if successful:
        avg_loss = sum(r["avg_loss_rate"] for r in successful) / len(successful)
        max_loss = max(r["max_loss_rate"] for r in successful)
        print(f"Average loss rate: {avg_loss*100:.2f}%")
        print(f"Max loss rate: {max_loss*100:.2f}%")


if __name__ == "__main__":
    main()
