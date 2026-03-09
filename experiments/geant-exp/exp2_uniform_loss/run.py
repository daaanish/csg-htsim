"""
Experiment 2: Uniform Loss Model
==================================
Tests single-W routing with overload.
Measures per-tunnel and per-pair effective flow and compares against
the hop-by-hop uniform-loss math model.

Edit the CONFIG section below, then run:
    python3 experiments/geant-exp/exp2_uniform_loss/run.py
"""

import csv
import os
import subprocess
import sys
import builtins
from datetime import datetime

# ── PATHS ──────────────────────────────────────────────────────────────────
ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
HTSIM     = os.path.join(ROOT, "sim/datacenter/htsim_cbr")
TOPO      = os.path.join(ROOT, "experiments/geant-exp/topo/geant_small.json")
EXP_DIR    = os.path.dirname(__file__)
OUT_DIR    = os.path.join(EXP_DIR, "output")
TM_OUT     = os.path.join(OUT_DIR, "traffic.tm")

# ── CONFIG ─────────────────────────────────────────────────────────────────
SIM_END        = 2.0          # simulation duration (seconds)
QUEUE_SIZE_PKTS = 15          # queue size in packets
QUEUE_TYPE      = "random"    # "composite" or "random"

# Each pair: src, dst, d_st (Mbps), W (path weights, sum=1), path_indices
PAIRS = [
    {
        "src": 0, "dst": 21,
        "d_st": 50,                  # 50 Mbps (will overload path 0's 24 Mbps bottleneck)
        "W": [0.6, 0.4],             # 60% on path 0, 40% on path 1
        "path_indices": [0, 1],
    },
    # Add more pairs here...
]

# ── RUN ────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "experiments/geant-exp/common"))
from load_sys_data import write_tm_file
from parse_results import build_results, aggregate_by_tunnel, print_tunnels
from predict_loss import (aggregate_predictions_by_pair, compute_predicted_loss,
                          get_runtime_path_hops, print_comparison,
                          print_pair_comparison)


def build_exact_rate_entries(pairs):
    """Build one exact-rate TM entry per active tunnel."""
    entries = []
    summaries = []
    for p in pairs:
        src = p["src"]
        dst = p["dst"]
        d_st = float(p["d_st"])
        weights = p["W"]
        path_indices = p["path_indices"]

        active_paths = 0
        for k, pidx in enumerate(path_indices):
            weight = weights[k] if k < len(weights) else 0.0
            volume = weight * d_st
            if volume <= 0:
                continue
            entries.append({
                "src": src,
                "dst": dst,
                "path_idx": pidx,
                "volume_mbps": volume,
            })
            active_paths += 1

        summaries.append({
            "src": src,
            "dst": dst,
            "d_st": d_st,
            "active_paths": active_paths,
            "path_indices": list(path_indices),
        })

    total_demand_mbps = sum(float(p["d_st"]) for p in pairs)
    summary = {
        "total_pairs": len([p for p in pairs if p["d_st"] > 0]),
        "overflow_pairs": 0,
        "total_demand_mbps": total_demand_mbps,
        "total_volume_mbps": total_demand_mbps,
    }
    return entries, summaries, summary


def compute_flow_size_bytes(entries):
    """Return a flow size that keeps every exact-rate tunnel active for SIM_END."""
    max_rate = max((e["volume_mbps"] for e in entries), default=1.0)
    return int(max_rate * SIM_END * 1e6 / 8) + 1_500


def aggregate_by_pair(results):
    """Aggregate parsed flow results to per-pair totals."""
    pair_totals = {}
    for r in results:
        key = (r["src"], r["dst"])
        if key not in pair_totals:
            pair_totals[key] = {"sent": 0, "delivered": 0}
        pair_totals[key]["sent"] += r["sent"]
        pair_totals[key]["delivered"] += r["delivered"]
    return pair_totals


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Open log file — mirror all print output to both terminal and log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(OUT_DIR, f"run_{timestamp}.txt")
    log_file = open(log_path, "w")

    # Local print wrapper for this function scope only.
    # Keeps terminal output unchanged and duplicates it to log_file.
    def print(*args, **kwargs):
        builtins.print(*args, **kwargs)
        log_kwargs = dict(kwargs)
        log_kwargs["file"] = log_file
        builtins.print(*args, **log_kwargs)
        log_file.flush()

    print("=" * 70)
    print("  Experiment 2: Uniform Loss Model")
    print("=" * 70)
    print(f"  Topology:   {os.path.basename(TOPO)}")
    print(f"  Sim end:    {SIM_END}s")
    print(f"  Queue size: {QUEUE_SIZE_PKTS} packets ({QUEUE_TYPE})")
    print()

    # Step 1: Generate exact-rate .tm file
    entries, summaries, summary = build_exact_rate_entries(PAIRS)
    flow_size = compute_flow_size_bytes(entries)
    total_flows, flow_entries = write_tm_file(TM_OUT, entries, flow_size, summary)

    print(f"  Generated {TM_OUT}")
    print(f"  Flow size:   {flow_size:,} bytes")
    print(f"  Total flows: {total_flows}")
    for s in summaries:
        print(f"    {s['src']}->{s['dst']}: d_st={s['d_st']:.1f} "
              f"active_paths={s['active_paths']} paths={s['path_indices']}")
    print()

    # Step 2: Run htsim
    cmd = [HTSIM, "-json_topo", TOPO, "-tm", TM_OUT,
           "-q", str(QUEUE_SIZE_PKTS), "-queue_type", QUEUE_TYPE,
           "-end", str(SIM_END)]
    print(f"  Running: {' '.join(os.path.basename(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    if result.returncode != 0:
        print(f"  ERROR: htsim exited with code {result.returncode}")
        print(output[-2000:])
        print(f"  Log file:   {log_path}")
        log_file.close()
        return
    print(f"  htsim finished.")

    # Step 3: Parse results
    results = build_results(output, TM_OUT)
    tunnels = aggregate_by_tunnel(results)
    pair_totals = aggregate_by_pair(results)

    path_hops = get_runtime_path_hops(PAIRS, TOPO, HTSIM, k=4)
    rate_lookup = {idx + 1: fe["volume_mbps"] for idx, fe in enumerate(flow_entries)}

    flow_csv = os.path.join(OUT_DIR, "results_per_flow.csv")
    with open(flow_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["flow_id", "src", "dst", "path_idx", "path_hops",
                    "input_rate_mbps", "sent_bytes", "delivered_bytes",
                    "delivered_mbps", "loss_bytes", "loss_pct"])
        for r in results:
            fid = r["flow_id"]
            pidx = r["path_idx"]
            sent = r["sent"]
            delivered = r["delivered"]
            loss = sent - delivered
            loss_pct = loss / sent * 100 if sent > 0 else 0.0
            delivered_mbps = delivered * 8 / (SIM_END * 1e6)
            w.writerow([
                fid, r["src"], r["dst"], pidx,
                path_hops.get((r["src"], r["dst"], pidx), ""),
                f"{rate_lookup.get(fid, 0.0):.4f}",
                sent, delivered, f"{delivered_mbps:.4f}",
                loss, f"{loss_pct:.2f}",
            ])
    print(f"  Wrote {flow_csv}")

    tunnel_csv = os.path.join(OUT_DIR, "results_per_tunnel.csv")
    with open(tunnel_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src", "dst", "path_idx", "path_hops", "num_flows",
                    "input_rate_mbps", "sent_bytes", "delivered_bytes",
                    "delivered_mbps", "loss_bytes", "loss_pct"])
        for t in tunnels:
            key = (t["src"], t["dst"], t["path_idx"])
            input_rate = sum(fe["volume_mbps"] for fe in flow_entries
                             if fe["src"] == t["src"]
                             and fe["dst"] == t["dst"]
                             and fe["path_idx"] == t["path_idx"])
            sent = t["total_sent"]
            delivered = t["total_delivered"]
            loss = sent - delivered
            loss_pct = loss / sent * 100 if sent > 0 else 0.0
            delivered_mbps = delivered * 8 / (SIM_END * 1e6)
            w.writerow([
                t["src"], t["dst"], t["path_idx"], path_hops.get(key, ""),
                t["num_flows"], f"{input_rate:.4f}",
                sent, delivered, f"{delivered_mbps:.4f}",
                loss, f"{loss_pct:.2f}",
            ])
    print(f"  Wrote {tunnel_csv}")

    pair_csv = os.path.join(OUT_DIR, "results_per_pair.csv")
    with open(pair_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src", "dst", "input_rate_mbps", "sent_bytes",
                    "delivered_bytes", "delivered_mbps", "loss_bytes", "loss_pct"])
        for (src, dst), vals in sorted(pair_totals.items()):
            input_rate = sum(float(p["d_st"]) for p in PAIRS if p["src"] == src and p["dst"] == dst)
            sent = vals["sent"]
            delivered = vals["delivered"]
            loss = sent - delivered
            loss_pct = loss / sent * 100 if sent > 0 else 0.0
            delivered_mbps = delivered * 8 / (SIM_END * 1e6)
            w.writerow([
                src, dst, f"{input_rate:.4f}", sent, delivered,
                f"{delivered_mbps:.4f}", loss, f"{loss_pct:.2f}",
            ])
    print(f"  Wrote {pair_csv}")

    print_tunnels(tunnels, "Exp2: Per-Tunnel Effective Flow (htsim)")

    # Step 4: Compare against math model
    predictions = compute_predicted_loss(PAIRS, TOPO, HTSIM, SIM_END, k=4)
    pair_predictions = aggregate_predictions_by_pair(predictions)
    print_comparison(predictions, tunnels, SIM_END)
    print_pair_comparison(pair_predictions, pair_totals, SIM_END)
    print()
    print(f"  Log file:   {log_path}")
    log_file.close()


if __name__ == "__main__":
    main()
