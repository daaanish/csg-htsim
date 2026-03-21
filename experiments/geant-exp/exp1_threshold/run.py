"""
Experiment 1: Threshold Routing -> MaxEffFlow in htsim vs SYS-sim
======================================================
Loads SYS output (W1, W2, T_st) and GEANT TM demands,
generates htsim traffic, and measures per-pair effective flow.

Key output: MaxEffFlow = sum of all delivered traffic across all pairs.

Usage:
    # Run ALL evaluation TMs for index 0
    python3 experiments/geant-exp/exp1_threshold/run.py --idx 0

    # Specify index and a single TM
    python3 experiments/geant-exp/exp1_threshold/run.py --idx 0 --tm 7506
"""

import subprocess, sys, os, argparse, re, csv
import builtins
from datetime import datetime

# ── PATHS ──────────────────────────────────────────────────────────────────
ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
HTSIM     = os.path.join(ROOT, "sim/datacenter/htsim_cbr")
TOPO      = os.path.join(ROOT, "experiments/geant-exp/topo/geant.json")
EXP_DIR   = os.path.dirname(os.path.abspath(__file__))

# ── CONFIG ─────────────────────────────────────────────────────────────────
SIM_END         = 2.0         # simulation duration (seconds)
QUEUE_SIZE_PKTS = 15          # queue size in packets
QUEUE_TYPE      = "random"    # "composite" (NDP-style) or "random" (tail-drop)

# ── IMPORTS ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "experiments/geant-exp/common"))
from load_sys_data import (load_weights, load_tm, compute_volumes,
                           write_tm_file, sys_data_to_tm_numbers,
                           pair_index_to_src_dst, load_path_hops,
                           N_PAIRS, K_PATHS)
from parse_results import (build_results, aggregate_by_tunnel,
                           print_results, print_tunnels)


def run_experiment(sys_idx, tm_num, eval_tms):
    """Runs the htsim experiment for a single TM."""
    
    # Create output directory: output/idx{N}_tm{M}/
    out_dir = os.path.join(EXP_DIR, "output", f"idx{sys_idx}_tm{tm_num}")
    os.makedirs(out_dir, exist_ok=True)
    tm_out = os.path.join(out_dir, "traffic.tm")

    # Open log file — mirror all print output to both terminal and log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(out_dir, f"run_{timestamp}.txt")
    log_file = open(log_path, "w")

    # Local print wrapper
    def log_print(*args, **kwargs):
        builtins.print(*args, **kwargs)
        log_kwargs = dict(kwargs)
        log_kwargs["file"] = log_file
        builtins.print(*args, **log_kwargs)
        log_file.flush()

    # ── Header ─────────────────────────────────────────────────────────────
    log_print("=" * 70)
    log_print(f"  Experiment 1: W1, W2, T_st (Threshold) Routing")
    log_print("=" * 70)
    log_print(f"  Topology:     {os.path.basename(TOPO)}")
    log_print(f"  sys_data idx: {sys_idx}")
    log_print(f"  TM number:    {tm_num}")
    log_print(f"  Eval TMs:     {eval_tms}")
    log_print(f"  Output dir:   {out_dir}")
    log_print(f"  Sim end:      {SIM_END}s")
    log_print(f"  Queue:        {QUEUE_TYPE} (q={QUEUE_SIZE_PKTS})")
    log_print()

    # ── Step 1: Load SYS data and generate .tm ─────────────────────────────
    log_print("  Loading SYS data...")
    w1, w2, t_st = load_weights(sys_idx)
    demand = load_tm(tm_num)
    demand_mbps = demand * 1000.0

    entries, summary = compute_volumes(w1, w2, t_st, demand)

    max_rate = max(e["volume_mbps"] for e in entries) if entries else 1.0
    flow_size = int(max_rate * SIM_END * 1e6 / 8) + 1_000_000  # added margin
    log_print(f"  Flow size:    {flow_size:,} bytes "
          f"(auto-computed from max rate {max_rate:.1f} Mbps × {SIM_END}s)")

    total_flows, flow_entries = write_tm_file(
        tm_out, entries, flow_size, summary
    )

    log_print(f"  Generated {tm_out}")
    log_print(f"  Active pairs:   {summary['total_pairs']}")
    log_print(f"  Overflow pairs: {summary['overflow_pairs']} "
          f"(demand > T_st)")
    log_print(f"  Total demand:   {summary['total_demand_mbps']:.1f} Mbps "
          f"({summary['total_demand_mbps']/1000:.2f} Gbps)")
    log_print(f"  Total flows:    {total_flows}")
    log_print()

    if summary['overflow_pairs'] > 0:
        log_print("  Overflow pairs (d_st > T_st):")
        for i in range(N_PAIRS):
            d = demand_mbps[i]
            t = t_st[i]
            if d > t:
                src, dst = pair_index_to_src_dst(i)
                base = min(d, t)
                overflow = d - t
                log_print(f"    {src}->{dst}: demand={d:.1f} Mbps  "
                      f"T_st={t:.1f}  base={base:.1f}  overflow={overflow:.1f}")
        log_print()

    # ── Step 2: Run htsim ──────────────────────────────────────────────────
    cmd = [HTSIM, "-json_topo", TOPO, "-tm", tm_out,
           "-q", str(QUEUE_SIZE_PKTS), "-queue_type", QUEUE_TYPE,
           "-end", str(SIM_END)]
    log_print(f"  Running: {' '.join(os.path.basename(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr

    if result.returncode != 0:
        log_print(f"  ERROR: htsim exited with code {result.returncode}")
        log_print(output[-2000:])
        log_file.close()
        return

    log_print("  htsim finished.\n")

    # ── Step 3: Parse results ──────────────────────────────────────────────
    results = build_results(output, tm_out)
    rate_lookup = {i + 1: fe["volume_mbps"] for i, fe in enumerate(flow_entries)}
    demand_lookup = {pair_index_to_src_dst(i): demand_mbps[i] for i in range(N_PAIRS)}
    path_hops = load_path_hops()

    flow_csv = os.path.join(out_dir, "results_per_flow.csv")
    with open(flow_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["flow_id", "src", "dst", "path_idx", "path_hops",
                     "demand_mbps", "rate_mbps", "sent_bytes", "delivered_bytes",
                     "loss_bytes", "loss_pct"])
        for r in results:
            fid, pidx = r.get("flow_id", 0), r.get("path_idx", -1)
            loss = r["sent"] - r["delivered"]
            loss_pct = loss / r["sent"] * 100 if r["sent"] > 0 else 0
            hops = path_hops.get((r["src"], r["dst"], pidx), "")
            rate = rate_lookup.get(fid, 0)
            pair_demand = demand_lookup.get((r["src"], r["dst"]), 0)
            w.writerow([fid, r["src"], r["dst"], pidx, hops,
                        f"{pair_demand:.4f}", f"{rate:.4f}", r["sent"], r["delivered"],
                        loss, f"{loss_pct:.2f}"])
    log_print(f"  Wrote {flow_csv}")

    tunnels = aggregate_by_tunnel(results)
    tunnel_csv = os.path.join(out_dir, "results_per_tunnel.csv")
    with open(tunnel_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src", "dst", "path_idx", "path_hops",
                     "demand_mbps", "sent_bytes", "delivered_bytes", "loss_bytes", "loss_pct"])
        for t in tunnels:
            loss = t["total_sent"] - t["total_delivered"]
            loss_pct = loss / t["total_sent"] * 100 if t["total_sent"] > 0 else 0
            hops = path_hops.get((t["src"], t["dst"], t["path_idx"]), "")
            pair_demand = demand_lookup.get((t["src"], t["dst"]), 0)
            w.writerow([t["src"], t["dst"], t["path_idx"], hops,
                        f"{pair_demand:.4f}", t["total_sent"], t["total_delivered"],
                        loss, f"{loss_pct:.2f}"])
    log_print(f"  Wrote {tunnel_csv}")

    pair_totals = {}
    for r in results:
        key = (r["src"], r["dst"])
        if key not in pair_totals:
            pair_totals[key] = {"sent": 0, "delivered": 0}
        pair_totals[key]["sent"] += r["sent"]
        pair_totals[key]["delivered"] += r["delivered"]

    pair_csv = os.path.join(out_dir, "results_per_pair.csv")
    with open(pair_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src", "dst", "demand_mbps", "sent_bytes", "delivered_bytes",
                     "loss_bytes", "loss_pct"])
        for (src, dst), t in sorted(pair_totals.items()):
            loss = t["sent"] - t["delivered"]
            loss_pct = loss / t["sent"] * 100 if t["sent"] > 0 else 0
            pair_demand = demand_lookup.get((src, dst), 0)
            w.writerow([src, dst, f"{pair_demand:.4f}", t["sent"], t["delivered"],
                        loss, f"{loss_pct:.2f}"])
    log_print(f"  Wrote {pair_csv}\n")

    # ── Step 4: Key metrics ────────────────────────────────────────────────
    total_sent = sum(v["sent"] for v in pair_totals.values())
    total_delivered = sum(v["delivered"] for v in pair_totals.values())
    total_loss = total_sent - total_delivered

    eff_flow_mbps = total_delivered * 8 / (SIM_END * 1e6)
    eff_flow_gbps = eff_flow_mbps / 1000.0
    sent_rate_mbps = total_sent * 8 / (SIM_END * 1e6)

    log_print("=" * 70)
    log_print("  KEY RESULTS")
    log_print("=" * 70)
    log_print(f"  Total Sent:      {total_sent:>15,} bytes  ({sent_rate_mbps:,.1f} Mbps)")
    log_print(f"  Total Delivered: {total_delivered:>15,} bytes  ({eff_flow_mbps:,.1f} Mbps)")
    log_print(f"  Total Loss:      {total_loss:>15,} bytes")
    if total_sent > 0:
        log_print(f"  Delivery Ratio:  {total_delivered/total_sent*100:>14.2f}%")
        log_print(f"  Loss Ratio:      {total_loss/total_sent*100:>14.2f}%")
    log_print(f"\n  >>> MaxEffFlow = {eff_flow_mbps:,.2f} Mbps  ({eff_flow_gbps:,.4f} Gbps)\n")

    # ── Step 5: Per-pair breakdown ─────────────────────────────────────────
    lossy = [(k, v) for k, v in pair_totals.items()
             if v["sent"] > 0 and v["delivered"] < v["sent"]]

    if lossy:
        log_print(f"  Pairs with loss ({len(lossy)} / {len(pair_totals)}):")
        log_print(f"  {'pair':>7}  {'sent':>14}  {'delivered':>14}  {'loss':>12}  {'loss%':>7}")
        log_print(f"  {'-'*7}  {'-'*14}  {'-'*14}  {'-'*12}  {'-'*7}")
        for (src, dst), t in sorted(lossy,
                key=lambda x: x[1]["sent"] - x[1]["delivered"], reverse=True):
            loss = t["sent"] - t["delivered"]
            loss_pct = loss / t["sent"] * 100
            log_print(f"  {src:>2}->{dst:<2}  {t['sent']:>14,}  "
                  f"{t['delivered']:>14,}  {loss:>12,}  {loss_pct:>6.1f}%")
    else:
        log_print("  No pairs experienced loss ???")
    
    log_print(f"\n  Log file:      {log_path}\n")
    log_file.close()


def main():
    parser = argparse.ArgumentParser(description="Exp1: threshold routing with SYS data")
    parser.add_argument("--idx", type=int, default=0, help="sys_data index (default: 0)")
    parser.add_argument("--tm", type=int, default=None,
                        help="Specific TM number. If omitted, runs ALL eval TMs for the index.")
    args = parser.parse_args()

    sys_idx = args.idx
    eval_tms = sys_data_to_tm_numbers(sys_idx)
    
    # If TM is specified, run that one. Otherwise, run all.
    tms_to_run = [args.tm] if args.tm is not None else eval_tms
    
    print(f"Starting experiment run for index: {sys_idx}")
    print(f"Traffic Matrices to process: {tms_to_run}\n")

    for tm_num in tms_to_run:
        print(f"--> Initiating run for TM {tm_num}...")
        run_experiment(sys_idx, tm_num, eval_tms)
        
    print(f"✅ All requested runs for index {sys_idx} completed.")

if __name__ == "__main__":
    main()