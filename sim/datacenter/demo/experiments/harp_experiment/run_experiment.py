#!/usr/bin/env python3
"""
Batch runner for HARP traffic matrix simulations using htsim_cbr.

This script uses QUANTIZED RATE AGGREGATION (QRA) to simulate variable demands:
- The simulator enforces a single global sending rate for all flows
- To approximate different demands, we use multiple parallel micro-flows
- Each micro-flow sends at a fixed "base rate" with a fixed flow size
- Demand approximation: k = ceil(demand_mbps / base_rate_mbps) micro-flows
- Effective bandwidth = k * base_rate_mbps

This script:
1. Converts CSV TMs to .tm format using QRA (multiple flows per OD pair)
2. Runs htsim_cbr for each TM
3. Aggregates micro-flow results back to OD-pair level statistics
4. Reports per-OD-pair throughput vs. original demand

Throughput calculation:
- Micro-flows are grouped by (src, dst) OD pair
- Aggregate throughput = sum of individual micro-flow throughputs
- Uses flow active time (first byte received to last byte received)
"""
import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import the converter
from csv_to_tm import csv_to_tm


def find_htsim_binary(script_dir: Path) -> Path:
    """Find htsim_cbr binary."""
    # Look in datacenter directory
    datacenter_dir = script_dir.parent.parent.parent  # demo/experiments/harp_experiment -> datacenter
    htsim = datacenter_dir / "htsim_cbr"
    
    if not htsim.exists():
        # Try to build it
        print("Building htsim_cbr...")
        result = subprocess.run(["make", "htsim_cbr"], cwd=str(datacenter_dir),
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to build htsim_cbr:\n{result.stderr}")
            sys.exit(1)
    
    return htsim


def find_parse_output(script_dir: Path) -> Path:
    """Find parse_output binary."""
    datacenter_dir = script_dir.parent.parent.parent
    sim_dir = datacenter_dir.parent
    parse_output = sim_dir / "parse_output"
    
    if not parse_output.exists():
        print("Building parse_output...")
        result = subprocess.run(["make", "parse_output"], cwd=str(sim_dir),
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to build parse_output:\n{result.stderr}")
            sys.exit(1)
    
    return parse_output


def run_simulation(htsim: Path, topo: Path, tm_path: Path, log_path: Path,
                   rate_mbps: float, end_sec: float, 
                   queue_type: str = "composite",
                   num_paths: Optional[int] = None,
                   use_multipath: Optional[bool] = None,
                   split_ratios: Optional[List[float]] = None,
                   single_path_index: Optional[int] = None) -> Tuple[int, str]:
    """
    Run a single htsim_cbr simulation.
    
    Args:
        num_paths: Limit number of ECMP paths (-paths)
        use_multipath: Enable multipath mode (-multipath)
        split_ratios: Custom split ratios for multipath (-split)
        single_path_index: Force specific path index for single path (-single_path_index)
    
    Returns (return_code, stdout)
    """
    cmd = [
        str(htsim),
        "-json_topo", str(topo),
        "-tm", str(tm_path),
        "-o", str(log_path),
        "-rate", str(rate_mbps),
        "-end", str(end_sec),
    ]
    
    if queue_type:
        cmd += ["-queue_type", queue_type]
    
    # Add routing configuration
    if use_multipath:
        cmd += ["-multipath"]
    
    if num_paths is not None:
        cmd += ["-paths", str(num_paths)]
    
    if split_ratios:
        split_str = ",".join(str(r) for r in split_ratios)
        cmd += ["-split", split_str]
    
    if single_path_index is not None:
        cmd += ["-single_path_index", str(single_path_index)]
    
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


def parse_throughput(parse_output_bin: Path, log_path: Path) -> Dict[Tuple[int,int,int], float]:
    """
    Parse throughput from log using parse_output -cbr -show.
    
    NOTE: This returns the sampled-average throughput, which may not be accurate
    for short flows. Use parse_flow_timings() for active-time throughput.
    
    Returns dict: (src, dst, flow_id) -> throughput_mbps
    """
    cmd = [str(parse_output_bin), str(log_path), "-cbr", "-show"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    tputs = {}
    # Format: "<Mbps> Mbps ... name cbr_sink_<src>_<dst>_<flowid>"
    pat = re.compile(r"^([0-9.]+)\s+Mbps.*name\s+cbr_sink_(\d+)_(\d+)_(\d+)")
    
    for line in result.stdout.splitlines():
        m = pat.match(line.strip())
        if m:
            mbps = float(m.group(1))
            src = int(m.group(2))
            dst = int(m.group(3))
            flow_id = int(m.group(4))
            tputs[(src, dst, flow_id)] = mbps
    
    return tputs


def parse_id_name_map(parse_output_bin: Path, log_path: Path) -> Dict[int, str]:
    """Return mapping from numeric ID to object name using parse_output -names."""
    cmd = [str(parse_output_bin), str(log_path), "-names"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    mapping = {}
    for line in result.stdout.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            i = int(parts[0])
        except Exception:
            continue
        mapping[i] = parts[1]
    return mapping


def parse_cbr_sink_timeseries(parse_output_bin: Path, log_path: Path) -> Dict[int, List[Tuple[float, int]]]:
    """
    Extract time series samples for CBR_SINK records.
    
    Returns: {sink_id: [(time_s, bytes_rcvd), ...]}
    """
    cmd = [str(parse_output_bin), str(log_path), "-ascii", "-filter", "Type CBR_SINK"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    series = {}
    # Example line: "123.456789000 Type CBR_SINK ID 66 Ev RATE BytesRcvd 10000 PktsRcvd 7 Rate 80000000"
    pat = re.compile(r"^(?P<time>[0-9]+\.[0-9]+)\s+Type CBR_SINK ID\s+(?P<id>\d+)\s+Ev RATE\s+BytesRcvd\s+(?P<bytes>\d+)\b")
    
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("Type CBR_SINK"):
            continue
        m = pat.match(line)
        if not m:
            continue
        t = float(m.group("time"))
        sid = int(m.group("id"))
        b = int(m.group("bytes"))
        series.setdefault(sid, []).append((t, b))
    
    # Ensure time order
    for sid in series:
        series[sid].sort(key=lambda x: x[0])
    
    return series


def compute_active_throughput(bytes_received: int, timeseries: List[Tuple[float, int]]) -> Dict:
    """
    Compute throughput based on flow active time (first to last byte received).
    
    Returns dict with:
        - start_time: when first bytes were received
        - end_time: when last bytes were received  
        - active_duration: end_time - start_time
        - active_throughput_mbps: bytes_received * 8 / active_duration / 1e6
    """
    result = {
        "start_time": None,
        "end_time": None,
        "active_duration": None,
        "active_throughput_mbps": None
    }
    
    if not timeseries or bytes_received == 0:
        return result
    
    # Find first and last time when bytes were actually being received
    prev_bytes = None
    start_t = None
    end_t = None
    
    for (t, b) in timeseries:
        if prev_bytes is None:
            prev_bytes = b
            continue
        if b > prev_bytes:  # Bytes increased -> flow was active
            if start_t is None:
                start_t = t
            end_t = t
        prev_bytes = b
    
    if start_t is not None and end_t is not None:
        result["start_time"] = start_t
        result["end_time"] = end_t
        duration = end_t - start_t
        result["active_duration"] = duration
        if duration > 0:
            result["active_throughput_mbps"] = (bytes_received * 8.0) / (duration * 1e6)
        else:
            # Flow completed within one sample interval - estimate based on sample period
            # Use the first sample interval as an upper bound on duration
            if len(timeseries) >= 2:
                sample_interval = timeseries[1][0] - timeseries[0][0]
                if sample_interval > 0:
                    # Use sample interval as approximate duration
                    result["active_throughput_mbps"] = (bytes_received * 8.0) / (sample_interval * 1e6)
    
    return result


def read_csv_demands(csv_path: Path, scale_factor: float = 1.0) -> Dict[Tuple[int, int], float]:
    """
    Read original demands from CSV file.
    
    Returns:
        Dict mapping (src, dst) -> demand_mbps
    """
    demands = {}
    with csv_path.open('r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = int(row['src'])
            dst = int(row['dst'])
            
            if 'demand_mbps' in row:
                demand_mbps = float(row['demand_mbps']) * scale_factor
            elif 'demand_Gbps' in row:
                demand_mbps = float(row['demand_Gbps']) * 1000 * scale_factor
            else:
                continue
            
            if src != dst and demand_mbps > 0:
                demands[(src, dst)] = demand_mbps
    
    return demands


def run_single_tm(args_tuple) -> Dict:
    """
    Process a single TM (for parallel execution) using Quantized Rate Aggregation.
    
    Returns a dict with TM results or error info.
    Results include:
    - flows: list of individual micro-flow stats
    - od_pairs: aggregated stats per (src, dst) pair
    """
    (tm_id, csv_path, tm_path, log_path, htsim, parse_output_bin, 
     topo, rate_mbps, end_sec, queue_type, num_nodes, 
     base_rate_mbps, flow_size_bytes, routing_config, scale_factor,
     split_ratios_file, pairs_dict_file, path_mapping_file, delete_logs) = args_tuple
    
    result = {
        "tm_id": tm_id,
        "success": False,
        "flows": [],
        "od_pairs": [],  # Aggregated results per OD pair
        "error": None
    }
    
    try:
        # Read original demands from CSV for comparison (with scale factor)
        original_demands = read_csv_demands(csv_path, scale_factor=scale_factor)
        
        # Convert CSV to TM using QRA if needed
        if not tm_path.exists():
            csv_to_tm(csv_path, tm_path, num_nodes=num_nodes,
                      base_rate_mbps=base_rate_mbps, flow_size_bytes=flow_size_bytes,
                      scale_factor=scale_factor,
                      split_ratios_file=split_ratios_file,
                      pairs_dict_file=pairs_dict_file,
                      path_mapping_file=path_mapping_file)
        
        # Run simulation
        log_path.parent.mkdir(parents=True, exist_ok=True)
        rc, stdout = run_simulation(
            htsim, topo, tm_path, log_path, 
            rate_mbps, end_sec, queue_type,
            num_paths=routing_config.get("num_paths"),
            use_multipath=routing_config.get("use_multipath"),
            split_ratios=routing_config.get("split_ratios"),
            single_path_index=routing_config.get("single_path_index")
        )
        
        if rc != 0:
            result["error"] = f"htsim_cbr failed with code {rc}"
            return result
        
        # Parse results
        flow_stats = parse_flow_stats(stdout)
        
        # Get ID->name mapping and timeseries for active-time throughput
        id_name = parse_id_name_map(parse_output_bin, log_path)
        name_id = {v: k for (k, v) in id_name.items()}
        sink_series = parse_cbr_sink_timeseries(parse_output_bin, log_path)
        
        # Also get sampled throughput as fallback
        sampled_tputs = parse_throughput(parse_output_bin, log_path)
        
        # Merge flow stats with throughput (using active-time calculation)
        for fs in flow_stats:
            key = (fs["src"], fs["dst"], fs["flow_id"])
            fs["bytes_dropped"] = max(0, fs["bytes_sent"] - fs["bytes_received"])
            fs["loss_rate"] = (fs["bytes_dropped"] / fs["bytes_sent"] 
                              if fs["bytes_sent"] > 0 else 0.0)
            
            # Look up sink timeseries
            sink_name = f"cbr_sink_{fs['src']}_{fs['dst']}_{fs['flow_id']}"
            sink_id = name_id.get(sink_name)
            
            if sink_id is not None and sink_id in sink_series:
                timing = compute_active_throughput(fs["bytes_received"], sink_series[sink_id])
                fs["start_time"] = timing["start_time"]
                fs["end_time"] = timing["end_time"]
                fs["active_duration"] = timing["active_duration"]
                fs["active_throughput_mbps"] = timing["active_throughput_mbps"]
            else:
                fs["start_time"] = None
                fs["end_time"] = None
                fs["active_duration"] = None
                fs["active_throughput_mbps"] = None
            
            # Use sampled throughput as fallback
            fs["sampled_throughput_mbps"] = sampled_tputs.get(key, 0.0)
            
            # Primary throughput: use active if available, else sampled
            if fs["active_throughput_mbps"] is not None:
                fs["throughput_mbps"] = fs["active_throughput_mbps"]
            else:
                fs["throughput_mbps"] = fs["sampled_throughput_mbps"]
        
        result["flows"] = flow_stats
        
        # Aggregate micro-flows by OD pair (this is the key QRA aggregation step)
        od_aggregates = defaultdict(lambda: {
            "src": 0, "dst": 0,
            "num_micro_flows": 0,
            "total_bytes_sent": 0,
            "total_bytes_received": 0,
            "total_bytes_dropped": 0,
            "throughputs": [],  # List of individual micro-flow throughputs
            "original_demand_mbps": 0.0,
            "expected_micro_flows": 0,
        })
        
        for fs in flow_stats:
            od_key = (fs["src"], fs["dst"])
            agg = od_aggregates[od_key]
            agg["src"] = fs["src"]
            agg["dst"] = fs["dst"]
            agg["num_micro_flows"] += 1
            agg["total_bytes_sent"] += fs["bytes_sent"]
            agg["total_bytes_received"] += fs["bytes_received"]
            agg["total_bytes_dropped"] += fs["bytes_dropped"]
            if fs["throughput_mbps"] is not None and fs["throughput_mbps"] > 0:
                agg["throughputs"].append(fs["throughput_mbps"])
        
        # Compute aggregate statistics and compare to original demands
        od_pair_results = []
        for od_key, agg in od_aggregates.items():
            original_demand = original_demands.get(od_key, 0.0)
            expected_flows = max(1, math.ceil(original_demand / base_rate_mbps)) if original_demand > 0 else 0
            
            # Aggregate throughput is sum of individual micro-flow throughputs
            aggregate_throughput = sum(agg["throughputs"])
            avg_micro_throughput = (aggregate_throughput / len(agg["throughputs"]) 
                                    if agg["throughputs"] else 0.0)
            
            od_result = {
                "src": agg["src"],
                "dst": agg["dst"],
                "original_demand_mbps": original_demand,
                "expected_micro_flows": expected_flows,
                "actual_micro_flows": agg["num_micro_flows"],
                "aggregate_throughput_mbps": aggregate_throughput,
                "avg_micro_throughput_mbps": avg_micro_throughput,
                "total_bytes_sent": agg["total_bytes_sent"],
                "total_bytes_received": agg["total_bytes_received"],
                "total_bytes_dropped": agg["total_bytes_dropped"],
                "loss_rate": (agg["total_bytes_dropped"] / agg["total_bytes_sent"]
                              if agg["total_bytes_sent"] > 0 else 0.0),
                "demand_satisfaction": (aggregate_throughput / original_demand
                                        if original_demand > 0 else 1.0),
            }
            od_pair_results.append(od_result)
        
        result["od_pairs"] = od_pair_results
        result["success"] = True
        
        # Delete log file to save storage (logs can be 50+ MB each)
        if delete_logs and log_path.exists():
            log_path.unlink()
        
    except Exception as e:
        import traceback
        result["error"] = f"{str(e)}\n{traceback.format_exc()}"
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run HARP TM simulations with htsim_cbr using Quantized Rate Aggregation"
    )
    parser.add_argument("--config", type=str, default="config.json",
                        help="Path to experiment config JSON")
    parser.add_argument("--csv-dir", type=str,
                        help="Override CSV directory from config")
    parser.add_argument("--topology", type=str,
                        help="Override topology path from config")
    parser.add_argument("--output-dir", type=str, default="output",
                        help="Output directory for results")
    parser.add_argument("--tm-ids", type=int, nargs="+",
                        help="Specific TM IDs to run")
    parser.add_argument("--tm-range", type=int, nargs=2, metavar=("START", "END"),
                        help="Range of TM IDs to run (inclusive)")
    parser.add_argument("--parallel", type=int, default=1,
                        help="Number of parallel simulations")
    parser.add_argument("--base-rate", type=float,
                        help="Override base_rate_mbps from config (QRA atomic rate)")
    parser.add_argument("--flow-size", type=int,
                        help="Override flow_size_bytes from config")
    parser.add_argument("--duration", type=float,
                        help="Override end_sec from config")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Scale factor for demands (e.g., 100 to multiply all demands by 100)")
    parser.add_argument("--split-ratios-dir", type=str,
                        help="Directory containing split_ratios_snapshot_{tm_id}.npy files")
    parser.add_argument("--pairs-dict", type=str,
                        help="Path to pairs dict .pkl file (maps OD pairs to indices)")
    parser.add_argument("--path-mapping", type=str,
                        help="Path to JSON file mapping Gurobi path indices to htsim indices")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only convert TMs, don't run simulations")
    parser.add_argument("--delete-logs", action="store_true", default=True,
                        help="Delete log files after parsing to save storage (default: True)")
    parser.add_argument("--keep-logs", action="store_true",
                        help="Keep log files (overrides --delete-logs)")
    
    args = parser.parse_args()
    
    script_dir = Path(__file__).resolve().parent
    
    # Load config
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = script_dir / config_path
    
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = {}
    
    # Resolve paths
    csv_dir = Path(args.csv_dir or config.get("csv_dir", ""))
    if not csv_dir.is_absolute():
        csv_dir = script_dir / csv_dir
    
    topo = Path(args.topology or config.get("topology", ""))
    if not topo.is_absolute():
        topo = script_dir / topo
    
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = script_dir / output_dir
    
    # Simulation parameters - using QRA model
    sim_config = config.get("simulation", {})
    
    # QRA parameters:
    # - base_rate_mbps: the atomic rate each micro-flow sends at (used with -rate)
    # - flow_size_bytes: size of each micro-flow
    base_rate_mbps = args.base_rate or sim_config.get("base_rate_mbps", 1.0)
    flow_size_bytes = args.flow_size or sim_config.get("flow_size_bytes", 1_000_000)
    
    # Duration should be long enough for all flows to complete
    # Each micro-flow takes flow_size_bytes * 8 / (base_rate_mbps * 1e6) seconds
    flow_duration = flow_size_bytes * 8 / (base_rate_mbps * 1e6)
    default_end_sec = flow_duration * 1.1  # 10% buffer
    end_sec = args.duration or sim_config.get("end_sec", default_end_sec)
    
    queue_type = sim_config.get("queue_type", "composite")
    num_nodes = config.get("num_nodes", 12)  # Abilene default
    scale_factor = args.scale
    
    # Split ratios configuration (for optimal Gurobi-based routing)
    split_ratios_dir = Path(args.split_ratios_dir) if args.split_ratios_dir else None
    pairs_dict_file = Path(args.pairs_dict) if args.pairs_dict else None
    path_mapping_file = Path(args.path_mapping) if args.path_mapping else None
    
    if split_ratios_dir:
        print(f"Using optimal split ratios from: {split_ratios_dir}")
    
    # Per-TM routing configuration
    per_tm_config = config.get("per_tm_config", {})
    default_routing = config.get("default_routing", {})
    
    # Create output directories
    tms_dir = output_dir / "tms"
    logs_dir = output_dir / "logs"
    results_dir = output_dir / "results"
    
    for d in [tms_dir, logs_dir, results_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    # Find binaries
    htsim = find_htsim_binary(script_dir)
    parse_output_bin = find_parse_output(script_dir)
    
    print(f"Using htsim_cbr: {htsim}")
    print(f"Using parse_output: {parse_output_bin}")
    print(f"Topology: {topo}")
    print(f"CSV directory: {csv_dir}")
    print(f"Output: {output_dir}")
    print(f"\nQuantized Rate Aggregation (QRA) parameters:")
    print(f"  base_rate_mbps = {base_rate_mbps}")
    print(f"  flow_size_bytes = {flow_size_bytes}")
    print(f"  flow_duration = {flow_duration:.3f}s")
    print(f"  simulation_end = {end_sec:.3f}s")
    print(f"  scale_factor = {scale_factor}")
    
    # Get list of TMs to process
    csv_files = sorted(csv_dir.glob("tm_*.csv"))
    tm_map = {}  # tm_id -> csv_path
    
    for csv_path in csv_files:
        try:
            tm_id = int(csv_path.stem.split('_')[1])
            tm_map[tm_id] = csv_path
        except (IndexError, ValueError):
            continue
    
    # Filter by requested TM IDs
    if args.tm_ids:
        tm_ids = [tid for tid in args.tm_ids if tid in tm_map]
    elif args.tm_range:
        start, end = args.tm_range
        tm_ids = [tid for tid in tm_map if start <= tid <= end]
    else:
        tm_ids = sorted(tm_map.keys())
    
    print(f"\nProcessing {len(tm_ids)} traffic matrices...")
    
    if args.dry_run:
        # Just convert TMs using QRA
        # Include scale in filename to avoid caching issues
        scale_suffix = f"_scale{scale_factor}" if scale_factor != 1.0 else ""
        splits_suffix = "_splits" if split_ratios_dir else ""
        for tm_id in tm_ids:
            csv_path = tm_map[tm_id]
            tm_path = tms_dir / f"tm_{tm_id}{scale_suffix}{splits_suffix}.tm"
            if not tm_path.exists():
                # Look up split ratios for this TM
                split_ratios_file = None
                if split_ratios_dir:
                    split_ratios_file = split_ratios_dir / f"split_ratios_snapshot_{tm_id}.npy"
                    if not split_ratios_file.exists():
                        split_ratios_file = None
                
                total_flows, od_pairs = csv_to_tm(
                    csv_path, tm_path, num_nodes=num_nodes,
                    base_rate_mbps=base_rate_mbps, flow_size_bytes=flow_size_bytes,
                    scale_factor=scale_factor,
                    split_ratios_file=split_ratios_file,
                    pairs_dict_file=pairs_dict_file,
                    path_mapping_file=path_mapping_file
                )
                split_info = " (with optimal splits)" if split_ratios_file else ""
                print(f"Converted tm_{tm_id}: {od_pairs} OD pairs -> {total_flows} micro-flows{split_info}")
        print("Dry run complete.")
        return
    
    # Prepare arguments for parallel execution
    # Include scale in filenames to avoid caching issues
    scale_suffix = f"_scale{scale_factor}" if scale_factor != 1.0 else ""
    splits_suffix = "_splits" if split_ratios_dir else ""
    task_args = []
    for tm_id in tm_ids:
        csv_path = tm_map[tm_id]
        tm_path = tms_dir / f"tm_{tm_id}{scale_suffix}{splits_suffix}.tm"
        log_path = logs_dir / f"tm_{tm_id}{scale_suffix}{splits_suffix}.dat"
        
        # Get routing config for this TM (or use default)
        tm_key = f"tm_{tm_id}"
        routing_config = per_tm_config.get(tm_key, default_routing.copy())
        
        # Look up split ratios for this TM
        split_ratios_file = None
        if split_ratios_dir:
            split_ratios_file = split_ratios_dir / f"split_ratios_snapshot_{tm_id}.npy"
            if not split_ratios_file.exists():
                split_ratios_file = None
        
        # Note: base_rate_mbps is passed to htsim as -rate parameter
        delete_logs = args.delete_logs and not args.keep_logs
        task_args.append((
            tm_id, csv_path, tm_path, log_path, htsim, parse_output_bin,
            topo, base_rate_mbps, end_sec, queue_type, num_nodes,
            base_rate_mbps, flow_size_bytes, routing_config, scale_factor,
            split_ratios_file, pairs_dict_file, path_mapping_file, delete_logs
        ))
    
    # Run simulations
    all_results = []
    
    if args.parallel > 1:
        with ProcessPoolExecutor(max_workers=args.parallel) as executor:
            futures = {executor.submit(run_single_tm, ta): ta[0] for ta in task_args}
            for future in as_completed(futures):
                tm_id = futures[future]
                try:
                    result = future.result()
                    all_results.append(result)
                    status = "OK" if result["success"] else f"FAILED: {result['error']}"
                    print(f"  tm_{tm_id}: {status}")
                except Exception as e:
                    print(f"  tm_{tm_id}: ERROR: {e}")
    else:
        for ta in task_args:
            tm_id = ta[0]
            result = run_single_tm(ta)
            all_results.append(result)
            status = "OK" if result["success"] else f"FAILED: {result['error']}"
            print(f"  tm_{tm_id}: {status}")
    
    # Write per-flow results CSV (micro-flow level) - simplified for loss analysis
    results_suffix = f"_scale{scale_factor}" if scale_factor != 1.0 else ""
    flow_csv = results_dir / f"all_micro_flows{results_suffix}.csv"
    with flow_csv.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "tm_id", "flow_id", "src", "dst", 
            "bytes_sent", "bytes_received", "bytes_dropped", "loss_rate"
        ])
        
        for result in sorted(all_results, key=lambda r: r["tm_id"]):
            if not result["success"]:
                continue
            for flow in result["flows"]:
                writer.writerow([
                    result["tm_id"],
                    flow["flow_id"],
                    flow["src"],
                    flow["dst"],
                    flow["bytes_sent"],
                    flow["bytes_received"],
                    flow["bytes_dropped"],
                    f"{flow['loss_rate']:.6f}"
                ])
    
    # Write OD-pair aggregated results CSV - simplified for loss analysis
    od_csv = results_dir / f"od_pairs{results_suffix}.csv"
    with od_csv.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "tm_id", "src", "dst", "demand_mbps",
            "bytes_sent", "bytes_received", "bytes_dropped", "loss_rate"
        ])
        
        for result in sorted(all_results, key=lambda r: r["tm_id"]):
            if not result["success"]:
                continue
            for od in result.get("od_pairs", []):
                writer.writerow([
                    result["tm_id"],
                    od["src"],
                    od["dst"],
                    f"{od['original_demand_mbps']:.3f}",
                    od["total_bytes_sent"],
                    od["total_bytes_received"],
                    od["total_bytes_dropped"],
                    f"{od['loss_rate']:.6f}"
                ])
    
    # Write summary CSV - simplified for loss analysis
    summary_csv = results_dir / f"summary{results_suffix}.csv"
    with summary_csv.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "tm_id", "num_od_pairs",
            "total_bytes_sent", "total_bytes_received", "total_bytes_dropped",
            "total_demand_mbps", "avg_loss_rate", "max_loss_rate"
        ])
        
        for result in sorted(all_results, key=lambda r: r["tm_id"]):
            if not result["success"]:
                writer.writerow([result["tm_id"], "ERROR", result["error"], 
                                 "", "", "", "", ""])
                continue
            
            od_pairs = result.get("od_pairs", [])
            if not od_pairs:
                continue
            
            total_sent = sum(od["total_bytes_sent"] for od in od_pairs)
            total_rcvd = sum(od["total_bytes_received"] for od in od_pairs)
            total_drop = sum(od["total_bytes_dropped"] for od in od_pairs)
            total_demand = sum(od["original_demand_mbps"] for od in od_pairs)
            avg_loss = total_drop / total_sent if total_sent > 0 else 0.0
            max_loss = max((od["loss_rate"] for od in od_pairs), default=0.0)
            
            writer.writerow([
                result["tm_id"],
                len(od_pairs),
                total_sent,
                total_rcvd,
                total_drop,
                f"{total_demand:.3f}",
                f"{avg_loss:.6f}",
                f"{max_loss:.6f}"
            ])
    
    # Print summary
    success = sum(1 for r in all_results if r["success"])
    failed = len(all_results) - success
    print(f"\nCompleted: {success} successful, {failed} failed")
    print(f"Results: {results_dir}")
    print(f"  - OD pairs (primary): {od_csv}")
    print(f"  - Micro-flows: {flow_csv}")
    print(f"  - Summary: {summary_csv}")


if __name__ == "__main__":
    main()
