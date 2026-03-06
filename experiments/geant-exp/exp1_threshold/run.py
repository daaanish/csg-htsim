"""
Experiment 1: Two-Stage Threshold Routing
==========================================
Tests W1/W2 threshold-based routing and measures effective flow at receiver.

Edit the CONFIG section below, then run:
    python3 experiments/geant-exp/exp1_threshold/run.py
"""

import subprocess, sys, os

# ── PATHS ──────────────────────────────────────────────────────────────────
ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
HTSIM     = os.path.join(ROOT, "sim/datacenter/htsim_cbr")
TOPO      = os.path.join(ROOT, "experiments/geant-exp/topo/geant_small.json")
TM_OUT    = os.path.join(os.path.dirname(__file__), "traffic.tm")

# ── CONFIG ─────────────────────────────────────────────────────────────────
NODES          = 22
RATE_MBPS      = 10           # per-flow CBR rate
FLOW_SIZE      = 1_250_000    # bytes per flow (common to all)
SIM_END        = 2.0          # simulation duration (seconds)
QUEUE_SIZE_PKTS = 15          # queue size in packets
QUEUE_TYPE      = "random"    # "composite" (NDP-style) or "random" (tail-drop)

# Each pair: src, dst, d_st (Mbps), T_st (Mbps), W1, W2, path_indices
PAIRS = [
    {
        "src": 0, "dst": 21,
        "d_st": 50,           # total demand: 50 Mbps
        "T_st": 24,           # threshold: 24 Mbps
        "W1": [0.6, 0.4],     # base weights (sum=1)
        "W2": [0.3, 0.7],     # overflow weights (sum=1)
        "path_indices": [0, 1],
    },
    # Add more pairs here...
]

# ── RUN ────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "experiments/geant-exp/common"))
from generate_tm import generate
from parse_results import build_results, aggregate_by_tunnel, print_results, print_tunnels


def main():
    print("=" * 70)
    print("  Experiment 1: Two-Stage Threshold Routing")
    print("=" * 70)
    print(f"  Topology:   {os.path.basename(TOPO)}")
    print(f"  Rate:       {RATE_MBPS} Mbps/flow")
    print(f"  Flow size:  {FLOW_SIZE:,} bytes")
    print(f"  Sim end:    {SIM_END}s")
    print()

    # Step 1: Generate .tm file
    total_flows, summaries = generate(
        PAIRS, RATE_MBPS, FLOW_SIZE, NODES, TM_OUT
    )
    print(f"  Generated {TM_OUT}")
    print(f"  Total flows: {total_flows}")
    for s in summaries:
        print(f"    {s['src']}->{s['dst']}: d_st={s['d_st']:.1f} T_st={s['T_st']:.1f} "
              f"flows={s['total_flows']} (ideal={s['ideal_flows']:.2f})")
    print()

    # Step 2: Run htsim
    cmd = [HTSIM, "-json_topo", TOPO, "-tm", TM_OUT,
           "-q", str(QUEUE_SIZE_PKTS), "-queue_type", QUEUE_TYPE,
           "-end", str(SIM_END)]
    print(f"  Running: {' '.join(os.path.basename(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(f"  htsim finished.")

    # Step 3: Parse results
    results = build_results(output, TM_OUT)
    print_results(results, "Exp1: Per-Flow Effective Flow")

    tunnels = aggregate_by_tunnel(results)
    print_tunnels(tunnels, "Exp1: Per-Tunnel Effective Flow")

    # Step 4: Per-pair summary
    print(f"\n{'='*70}")
    print(f"  Exp1: Per-Pair Demand vs Effective Flow")
    print(f"{'='*70}")
    pair_totals = {}
    for r in results:
        key = (r["src"], r["dst"])
        if key not in pair_totals:
            pair_totals[key] = {"sent": 0, "delivered": 0}
        pair_totals[key]["sent"] += r["sent"]
        pair_totals[key]["delivered"] += r["delivered"]

    for (src, dst), t in sorted(pair_totals.items()):
        s = next(x for x in summaries if x["src"] == src and x["dst"] == dst)
        eff_ratio = t["delivered"] / t["sent"] if t["sent"] > 0 else 0
        print(f"  {src}->{dst}: demand={s['d_st']:.1f} Mbps  "
              f"sent={t['sent']:,}  delivered={t['delivered']:,}  "
              f"effective={eff_ratio:.2%}")
    print()


if __name__ == "__main__":
    main()
