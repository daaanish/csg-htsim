"""
Experiment 3: RandomQueue Behavior Verification
=================================================
Runs 6 targeted scenarios on a single bottleneck link to understand
exactly how RandomQueue drops packets.

RandomQueue has three drop mechanisms (randomqueue.cpp):
  1. PLR: configurable random loss rate (_plr), default 0
  2. Stochastic zone: when queuesize > (maxsize - RANDOM_BUFFER*pkt_size),
     each arriving packet has 10% drop probability
  3. Tail-drop: when queuesize + pkt_size > maxsize, hard drop

With -q 15 (= 15 packets), RANDOM_BUFFER = 3 packets:
  - Packets 1-12: zone 0 (no drop)
  - Packets 12-15: zone 1 (10% stochastic drop)
  - Above 15: zone 2 (hard tail-drop)

Each scenario uses a single-hop path (r1->r16, cap=24 Mbps on geant_small)
with varying load levels.

Edit CONFIG below, then:
    python3 experiments/geant-exp/exp3_queue_test/run.py
"""

import subprocess, sys, os

# ── PATHS ──────────────────────────────────────────────────────────────────
ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
HTSIM     = os.path.join(ROOT, "sim/datacenter/htsim_cbr")
TOPO      = os.path.join(ROOT, "experiments/geant-exp/topo/geant_small.json")
TM_DIR    = os.path.dirname(__file__)

# ── CONFIG ─────────────────────────────────────────────────────────────────
NODES          = 22
SIM_END        = 2.0
BOTTLENECK_CAP = 24           # r1->r16 link capacity in geant_small (Mbps)

# Scenarios: each has a name, rate per flow, number of flows,
# queue size in packets, and expected behavior.
# All flows go from src=0 (r1) to dst=15 (r16) — single hop, single edge.
SCENARIOS = [
    {
        "name": "1. Under capacity (no loss expected)",
        "rate": 10, "num_flows": 2, "queue_pkts": 15,
        "total_mbps": 20,  # 20 < 24
        "expect": "0% loss — load under capacity",
    },
    {
        "name": "2. Exactly at capacity",
        "rate": 12, "num_flows": 2, "queue_pkts": 15,
        "total_mbps": 24,  # 24 == 24
        "expect": "~0% loss — load equals capacity",
    },
    {
        "name": "3. 25% over capacity",
        "rate": 10, "num_flows": 3, "queue_pkts": 15,
        "total_mbps": 30,  # 30 > 24, U=1.25
        "expect": "~20% loss — (30-24)/30 = 20%",
    },
    {
        "name": "4. 100% over capacity",
        "rate": 12, "num_flows": 4, "queue_pkts": 15,
        "total_mbps": 48,  # 48 > 24, U=2.0
        "expect": "~50% loss — (48-24)/48 = 50%",
    },
    {
        "name": "5. Same as #3 but tiny queue (q=1)",
        "rate": 10, "num_flows": 3, "queue_pkts": 1,
        "total_mbps": 30,  # U=1.25
        "expect": "~20%+ loss — less buffering may change slightly",
    },
    {
        "name": "6. Same as #3 but large queue (q=100)",
        "rate": 10, "num_flows": 3, "queue_pkts": 100,
        "total_mbps": 30,  # U=1.25
        "expect": "~20% loss — large buffer absorbs bursts",
    },
]

# ── RUN ────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "experiments/geant-exp/common"))
from parse_results import parse_htsim_output


def flow_size_for_rate(rate_mbps):
    """Return flow size large enough to keep a flow active for SIM_END."""
    return int(rate_mbps * SIM_END * 1e6 / 8) + 1_500


def write_simple_tm(filename, num_flows, rate, flow_size_bytes):
    """Write a TM file with N flows from r1 (0) to r16 (15), single-hop."""
    lines = [
        f"# Scenario: {num_flows} flows @ {rate} Mbps each = {num_flows*rate} Mbps",
        f"# Flow size: {flow_size_bytes} bytes for {SIM_END}s duration",
        f"Nodes {NODES}",
        f"Connections {num_flows}",
    ]
    for i in range(1, num_flows + 1):
        # r1=0, r16=15; path 0 is direct r1->r16
        lines.append(f"0->15 id {i} start 0 size {flow_size_bytes} rate {rate} paths_idx 0")
    with open(filename, "w") as f:
        f.write("\n".join(lines) + "\n")
    return filename


def run_scenario(scenario):
    """Run one scenario and return (total_sent, total_delivered, loss%)."""
    rate = scenario["rate"]
    n = scenario["num_flows"]
    q = scenario["queue_pkts"]
    flow_size_bytes = flow_size_for_rate(rate)

    tm_file = os.path.join(TM_DIR, f"scenario.tm")
    write_simple_tm(tm_file, n, rate, flow_size_bytes)

    cmd = [HTSIM, "-json_topo", TOPO, "-tm", tm_file,
           "-q", str(q), "-queue_type", "random",
           "-end", str(SIM_END)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr

    flows = parse_htsim_output(output)
    total_sent = sum(f["sent"] for f in flows)
    total_delivered = sum(f["delivered"] for f in flows)
    loss = (total_sent - total_delivered) / total_sent if total_sent > 0 else 0

    return total_sent, total_delivered, loss, flows


def main():
    print("=" * 75)
    print("  Experiment 3: RandomQueue Behavior Verification")
    print("=" * 75)
    print(f"  Bottleneck: r1->r16 at {BOTTLENECK_CAP} Mbps (geant_small)")
    print(f"  Single hop tests — isolates queue behavior from multi-hop effects")
    print()

    results = []
    for s in SCENARIOS:
        sent, delivered, loss, flows = run_scenario(s)
        predicted = max(0, (s["total_mbps"] - BOTTLENECK_CAP)) / s["total_mbps"]
        results.append({
            "scenario": s, "sent": sent, "delivered": delivered,
            "loss": loss, "predicted": predicted, "flows": flows,
        })

    # Summary table
    print(f"  {'#':>2} {'Load':>6} {'U':>5} {'q':>4}  "
          f"{'Predicted':>10} {'Actual':>10} {'Delta':>8}  Notes")
    print(f"  {'-'*2} {'-'*6} {'-'*5} {'-'*4}  "
          f"{'-'*10} {'-'*10} {'-'*8}  {'-'*30}")

    for r in results:
        s = r["scenario"]
        U = s["total_mbps"] / BOTTLENECK_CAP
        delta = r["predicted"] - r["loss"]
        print(f"  {s['name'][:2]:>2} {s['total_mbps']:>5}M {U:>4.2f} {s['queue_pkts']:>4}  "
              f"{r['predicted']:>9.2%} {r['loss']:>9.2%} {delta:>+7.2%}  "
              f"{s['expect']}")

    # Per-flow detail for scenario 3 (the reference case)
    print(f"\n{'='*75}")
    print(f"  Per-flow detail for Scenario 3 (25% overload, q=15)")
    print(f"{'='*75}")
    ref = results[2]
    for f in ref["flows"]:
        loss_pct = (f["sent"] - f["delivered"]) / f["sent"] * 100
        print(f"    flow {f['flow_id']}: sent={f['sent']:>12,}  "
              f"delivered={f['delivered']:>12,}  loss={loss_pct:.1f}%")

    # Per-flow detail for scenario 5 (same load, tiny queue)
    print(f"\n{'='*75}")
    print(f"  Per-flow detail for Scenario 5 (25% overload, q=1)")
    print(f"{'='*75}")
    ref = results[4]
    for f in ref["flows"]:
        loss_pct = (f["sent"] - f["delivered"]) / f["sent"] * 100
        print(f"    flow {f['flow_id']}: sent={f['sent']:>12,}  "
              f"delivered={f['delivered']:>12,}  loss={loss_pct:.1f}%")

    # Per-flow detail for scenario 6 (same load, big queue)
    print(f"\n{'='*75}")
    print(f"  Per-flow detail for Scenario 6 (25% overload, q=100)")
    print(f"{'='*75}")
    ref = results[5]
    for f in ref["flows"]:
        loss_pct = (f["sent"] - f["delivered"]) / f["sent"] * 100
        print(f"    flow {f['flow_id']}: sent={f['sent']:>12,}  "
              f"delivered={f['delivered']:>12,}  loss={loss_pct:.1f}%")
    print()


if __name__ == "__main__":
    main()
