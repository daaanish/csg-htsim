#!/usr/bin/env python3
"""Batch experiment: Run HTSIM for all TMs and correlate Gurobi MLU with loss.

Usage:
    python run_all_tm_experiment.py --sample 50  # Sample 50 TMs across MLU range
    python run_all_tm_experiment.py --all        # Run all 2000 TMs (slow)
"""
import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for saving plots
import matplotlib.pyplot as plt
import numpy as np


def load_gurobi_mlus(script_dir: Path) -> List[Tuple[int, float]]:
    """Load all (tm_id, gurobi_mlu) pairs from gurobi-MLUs directory.
    
    Returns list of (tm_id, mlu) sorted by tm_id.
    """
    gurobi_dir = script_dir / "gurobi-MLUs"
    vals_path = gurobi_dir / "optimal_values.txt"
    names_path = gurobi_dir / "filenames.txt"

    if not vals_path.exists() or not names_path.exists():
        raise FileNotFoundError("gurobi-MLUs directory missing required files")

    # Read MLUs
    mlus = []
    with vals_path.open() as f:
        for line in f:
            try:
                mlus.append(float(line.strip()))
            except ValueError:
                mlus.append(None)

    # Read TM ids from filenames (third column contains t<id>.pkl)
    tm_ids = []
    with names_path.open() as f:
        for line in f:
            parts = line.strip().split(',')
            tm_num = None
            if len(parts) >= 3:
                m = re.search(r't(\d+)\.pkl', parts[2])
                if m:
                    tm_num = int(m.group(1))
            tm_ids.append(tm_num)

    # Pair up valid entries
    pairs = []
    for idx, mlu in enumerate(mlus):
        if idx < len(tm_ids) and tm_ids[idx] is not None and mlu is not None:
            pairs.append((tm_ids[idx], mlu))

    # Sort by tm_id
    pairs.sort(key=lambda x: x[0])
    return pairs


def sample_tm_ids(pairs: List[Tuple[int, float]], n: int, high_mlu_threshold: float = 0.8) -> List[Tuple[int, float]]:
    """Sample n TMs stratified across the MLU range, always including high-MLU TMs.
    
    High-MLU TMs (above threshold) are always included since they're critical for validation.
    
    Returns list of (tm_id, mlu) tuples sorted by MLU.
    """
    if n >= len(pairs):
        return sorted(pairs, key=lambda x: x[1])
    
    # Separate high-MLU TMs (always include these)
    high_mlu = [p for p in pairs if p[1] >= high_mlu_threshold]
    low_mlu = [p for p in pairs if p[1] < high_mlu_threshold]
    
    # Sample from low-MLU TMs
    sorted_low = sorted(low_mlu, key=lambda x: x[1])
    remaining_slots = max(1, n - len(high_mlu))
    
    if remaining_slots >= len(sorted_low):
        sampled_low = sorted_low
    else:
        indices = np.linspace(0, len(sorted_low) - 1, remaining_slots, dtype=int)
        sampled_low = [sorted_low[i] for i in indices]
    
    # Combine and sort by MLU
    result = sampled_low + high_mlu
    return sorted(result, key=lambda x: x[1])


def run_single_tm(
    script_dir: Path,
    tm_id: int,
    output_dir: Path,
    duration_sec: float = 10.0,
    base_rate_mbps: float = 1.0,
    flow_size_bytes: int = 100_000_000,
    split_ratios_dir: Path = None,
    pairs_dict_file: Path = None,
    path_mapping_file: Path = None,
) -> Dict:
    """Run HTSIM for a single TM and return results."""
    
    cmd = [
        sys.executable,
        str(script_dir / "run_experiment.py"),
        "--config", str(script_dir / "config.json"),
        "--csv-dir", str(script_dir / "harp_csvs"),
        "--topology", str(script_dir / "abilene_harp.json"),
        "--output-dir", str(output_dir / f"tm_{tm_id}"),
        "--tm-ids", str(tm_id),
        "--duration", str(duration_sec),
        "--base-rate", str(base_rate_mbps),
        "--flow-size", str(flow_size_bytes),
    ]
    
    # Add split ratio arguments if provided
    if split_ratios_dir:
        cmd.extend(["--split-ratios-dir", str(split_ratios_dir)])
    if pairs_dict_file:
        cmd.extend(["--pairs-dict", str(pairs_dict_file)])
    if path_mapping_file:
        cmd.extend(["--path-mapping", str(path_mapping_file)])

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(script_dir))
    
    if result.returncode != 0:
        return {
            "success": False,
            "error": result.stderr[:500] if result.stderr else "Unknown error",
        }

    # Parse summary CSV
    summary_csv = output_dir / f"tm_{tm_id}" / "results" / "summary.csv"
    if not summary_csv.exists():
        return {"success": False, "error": f"Summary not found: {summary_csv}"}

    with summary_csv.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("tm_id") == str(tm_id):
                try:
                    return {
                        "success": True,
                        "num_od_pairs": int(row.get("num_od_pairs", 0)),
                        "total_bytes_sent": int(row.get("total_bytes_sent", 0)),
                        "total_bytes_received": int(row.get("total_bytes_received", 0)),
                        "total_bytes_dropped": int(row.get("total_bytes_dropped", 0)),
                        "total_demand_mbps": float(row.get("total_demand_mbps", 0)),
                        "avg_loss_rate": float(row.get("avg_loss_rate", 0)),
                        "max_loss_rate": float(row.get("max_loss_rate", 0)),
                    }
                except (ValueError, TypeError) as e:
                    return {"success": False, "error": f"Parse error: {e}"}

    return {"success": False, "error": "TM not found in summary"}


def generate_plot(results: List[Dict], output_path: Path):
    """Generate scatter plot of Gurobi MLU vs HTSIM Loss Rate."""
    
    # Filter successful results
    valid = [r for r in results if r.get("success")]
    if not valid:
        print("No successful results to plot")
        return

    mlus = [r["gurobi_mlu"] for r in valid]
    losses = [r["avg_loss_rate"] * 100 for r in valid]  # Convert to percentage

    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Scatter plot
    scatter = ax.scatter(mlus, losses, c=mlus, cmap='RdYlGn_r', s=60, alpha=0.7, edgecolors='black', linewidth=0.5)
    
    # Add colorbar
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Gurobi MLU', fontsize=11)
    
    # Add vertical line at MLU = 1.0
    ax.axvline(x=1.0, color='red', linestyle='--', linewidth=1.5, label='MLU = 1.0 (saturation)')
    
    # Labels and title
    ax.set_xlabel('Gurobi MLU (Optimal Link Utilization)', fontsize=12)
    ax.set_ylabel('HTSIM Loss Rate (%)', fontsize=12)
    ax.set_title('Validation: Gurobi MLU vs HTSIM Packet Loss', fontsize=14, fontweight='bold')
    
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    
    # Set axis limits
    ax.set_xlim(min(mlus) * 0.95, max(mlus) * 1.05)
    ax.set_ylim(-0.5, max(max(losses) * 1.1, 5))
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Saved plot: {output_path}")


def save_results_csv(results: List[Dict], output_path: Path):
    """Save all metrics to CSV for detailed debugging."""
    with output_path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "tm_id", "gurobi_mlu", "success",
            "num_od_pairs", "total_demand_mbps",
            "total_bytes_sent", "total_bytes_received", "total_bytes_dropped",
            "avg_loss_rate", "max_loss_rate",
            "goodput_ratio", "error"
        ])
        for r in results:
            # Calculate goodput ratio (received/sent)
            sent = r.get("total_bytes_sent", 0)
            received = r.get("total_bytes_received", 0)
            goodput_ratio = received / sent if sent > 0 else 0
            
            writer.writerow([
                r.get("tm_id", ""),
                r.get("gurobi_mlu", ""),
                r.get("success", False),
                r.get("num_od_pairs", ""),
                r.get("total_demand_mbps", ""),
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
    parser = argparse.ArgumentParser(description="Batch MLU vs Loss experiment")
    parser.add_argument("--sample", type=int, default=20, 
                        help="Number of TMs to sample (stratified by MLU)")
    parser.add_argument("--all", action="store_true", 
                        help="Run all TMs (overrides --sample)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Simulation duration in seconds")
    parser.add_argument("--output-dir", type=str, default="mlu_validation_output",
                        help="Output directory name")
    parser.add_argument("--split-ratios-dir", type=str, default="firebolt_dl/abilene_4_paths",
                        help="Directory containing split_ratios_snapshot_{tm_id}.npy files")
    parser.add_argument("--pairs-dict", type=str, default="firebolt_dl/abilene_4_paths_dict_cluster_0.pkl",
                        help="Path to pairs dict .pkl file (maps OD pairs to indices)")
    parser.add_argument("--path-mapping", type=str, default="firebolt_dl/gurobi_to_htsim_path_mapping.json",
                        help="Path to JSON file mapping Gurobi path indices to htsim indices")
    parser.add_argument("--optimal-splits", action="store_true",
                        help="Enable optimal split ratios from Gurobi (default: use shortest-path routing)")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Parse split ratio paths (only if --optimal-splits is set)
    if args.optimal_splits:
        split_ratios_dir = script_dir / args.split_ratios_dir if args.split_ratios_dir else None
        pairs_dict_file = script_dir / args.pairs_dict if args.pairs_dict else None
        path_mapping_file = script_dir / args.path_mapping if args.path_mapping else None
    else:
        split_ratios_dir = None
        pairs_dict_file = None
        path_mapping_file = None
    
    if split_ratios_dir:
        print(f"Using optimal split ratios from: {split_ratios_dir}")

    # Load all TM/MLU pairs
    print("Loading Gurobi MLU data...")
    all_pairs = load_gurobi_mlus(script_dir)
    print(f"Found {len(all_pairs)} TMs with Gurobi MLU values")
    print(f"MLU range: {min(p[1] for p in all_pairs):.3f} to {max(p[1] for p in all_pairs):.3f}")

    # Sample or use all
    if args.all:
        selected = all_pairs
    else:
        selected = sample_tm_ids(all_pairs, args.sample)
    
    print(f"\nRunning {len(selected)} TMs...")
    
    results = []
    for i, (tm_id, gurobi_mlu) in enumerate(selected):
        print(f"[{i+1}/{len(selected)}] TM {tm_id} (MLU={gurobi_mlu:.3f})...", end=" ", flush=True)
        
        result = run_single_tm(
            script_dir, tm_id, output_dir, 
            duration_sec=args.duration,
            split_ratios_dir=split_ratios_dir,
            pairs_dict_file=pairs_dict_file,
            path_mapping_file=path_mapping_file,
        )
        result["tm_id"] = tm_id
        result["gurobi_mlu"] = gurobi_mlu
        results.append(result)
        
        if result["success"]:
            print(f"loss={result['avg_loss_rate']*100:.2f}%")
        else:
            print(f"FAILED: {result.get('error', 'unknown')[:50]}")

    # Save results
    results_csv = output_dir / "mlu_vs_loss_results.csv"
    save_results_csv(results, results_csv)

    # Generate plot
    plot_path = output_dir / "mlu_vs_loss_plot.png"
    generate_plot(results, plot_path)

    # Print summary
    successful = [r for r in results if r["success"]]
    print(f"\n=== Summary ===")
    print(f"Total TMs: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(results) - len(successful)}")
    
    if successful:
        low_mlu = [r for r in successful if r["gurobi_mlu"] < 1.0]
        high_mlu = [r for r in successful if r["gurobi_mlu"] >= 1.0]
        
        if low_mlu:
            avg_loss_low = sum(r["avg_loss_rate"] for r in low_mlu) / len(low_mlu)
            print(f"Avg loss (MLU < 1.0): {avg_loss_low*100:.2f}% ({len(low_mlu)} TMs)")
        if high_mlu:
            avg_loss_high = sum(r["avg_loss_rate"] for r in high_mlu) / len(high_mlu)
            print(f"Avg loss (MLU >= 1.0): {avg_loss_high*100:.2f}% ({len(high_mlu)} TMs)")


if __name__ == "__main__":
    main()
