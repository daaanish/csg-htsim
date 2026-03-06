"""
Experiment 2: Uniform Loss Model
==================================
Tests single-W routing with intentional overload.
Measures per-tunnel effective flow and compares against (U-1)/U math model.

Edit the CONFIG section below, then run:
    python3 experiments/geant-exp/exp2_uniform_loss/run.py
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
FLOW_SIZE      = 1_250_000    # bytes per flow
SIM_END        = 2.0          # simulation duration (seconds)
QUEUE_SIZE_PKTS = 15          # queue size in packets
QUEUE_TYPE      = "random"    # "composite" (NDP-style, default) or "random" (simple tail-drop)

# For uniform loss: no threshold splitting.
# Set T_st very high so all traffic routes via W1 (= the single weight set W).
# W2 is unused since overflow = 0 when T_st >> d_st.
T_ST_INF       = 1e9

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
from generate_tm import generate
from parse_results import build_results, aggregate_by_tunnel, print_results, print_tunnels


def pairs_for_generator():
    """Convert exp2 pair format (single W) to generate_tm format (W1/W2)."""
    out = []
    for p in PAIRS:
        out.append({
            "src": p["src"], "dst": p["dst"],
            "d_st": p["d_st"],
            "T_st": T_ST_INF,        # no threshold → all traffic via W1
            "W1": p["W"],
            "W2": p["W"],             # unused (overflow = 0)
            "path_indices": p["path_indices"],
        })
    return out


def main():
    print("=" * 70)
    print("  Experiment 2: Uniform Loss Model")
    print("=" * 70)
    print(f"  Topology:   {os.path.basename(TOPO)}")
    print(f"  Rate:       {RATE_MBPS} Mbps/flow")
    print(f"  Flow size:  {FLOW_SIZE:,} bytes")
    print(f"  Sim end:    {SIM_END}s")
    print(f"  Queue size: {QUEUE_SIZE_PKTS} packets ({QUEUE_TYPE})")
    print()

    # Step 1: Generate .tm file
    gen_pairs = pairs_for_generator()
    total_flows, summaries = generate(
        gen_pairs, RATE_MBPS, FLOW_SIZE, NODES, TM_OUT
    )
    print(f"  Generated {TM_OUT}")
    print(f"  Total flows: {total_flows}")
    for s in summaries:
        print(f"    {s['src']}->{s['dst']}: d_st={s['d_st']:.1f} "
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
    tunnels = aggregate_by_tunnel(results)
    print_tunnels(tunnels, "Exp2: Per-Tunnel Effective Flow (htsim)")

    # Step 4: Compare against math model
    sys.path.insert(0, os.path.dirname(__file__))
    from predict_loss import compute_predicted_loss, print_comparison

    predictions = compute_predicted_loss(PAIRS, RATE_MBPS, TOPO, HTSIM)
    print_comparison(predictions, tunnels)
    print()


if __name__ == "__main__":
    main()
