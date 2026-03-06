#!/usr/bin/env python3
"""
Threshold-based Traffic-Engineering TM Generator for htsim.

Given per source-destination pair:
  D_st  – total raw application demand (bytes)
  T     – volume threshold (bytes)
  W1    – split-ratio weights for base traffic (up to T)           [need NOT sum to 1]
  W2    – split-ratio weights for overflow traffic (beyond T)      [need NOT sum to 1]

The generator computes per-path byte volumes and emits a .tm file that
htsim_cbr can consume directly, using the existing per-flow path-pinning
and flow-size mechanics.

Arithmetic per (s,d) pair:
  base     = min(D_st, T)
  overflow = max(0, D_st - T)
  For each unique path p across W1 and W2:
      bytes_p = W1[p] * base + W2[p] * overflow
  B_st = Σ bytes_p                                  (B_st ≤ D_st when Σ weights < 1)

Each non-zero bytes_p becomes a single-path flow in the output .tm file.

Usage:
  # From a JSON config (see --help for schema):
  python3 generate_te_tm.py --config config.json --output out.tm

  # Quick single-pair CLI mode:
  python3 generate_te_tm.py --nodes 4 --src 0 --dst 3   \\
      --D_st 50000000 --threshold 25000000               \\
      --W1 0.6,0.4 --W1_paths 0,1                        \\
      --W2 0.3,0.1 --W2_paths 0,1                        \\
      --rate 200 --output out.tm
"""

import argparse
import json
import math
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_pair_flows(pair_cfg, global_threshold, global_rate, global_start):
    """Return a list of flow dicts and the pair-level B_st value."""

    src       = pair_cfg["src"]
    dst       = pair_cfg["dst"]
    D_st      = float(pair_cfg["D_st"])
    T         = float(pair_cfg.get("threshold", global_threshold))
    rate_mbps = float(pair_cfg.get("rate_mbps", global_rate))
    start_ps  = pair_cfg.get("start_time_ps", global_start)

    # W1 / W2 configs
    w1_cfg = pair_cfg.get("W1", {})
    w2_cfg = pair_cfg.get("W2", {})

    w1_weights = w1_cfg.get("weights", [])
    w1_paths   = w1_cfg.get("path_indices", list(range(len(w1_weights))))
    w2_weights = w2_cfg.get("weights", [])
    w2_paths   = w2_cfg.get("path_indices", list(range(len(w2_weights))))

    assert len(w1_weights) == len(w1_paths), \
        f"W1 weights/paths length mismatch for {src}->{dst}"
    assert len(w2_weights) == len(w2_paths), \
        f"W2 weights/paths length mismatch for {src}->{dst}"

    base     = min(D_st, T)
    overflow = max(0.0, D_st - T)

    # Accumulate bytes per unique path index (merge base + overflow on same path)
    path_bytes = defaultdict(float)
    # Track per-path contribution from base and overflow (for debugging / summary)
    path_base = defaultdict(float)
    path_over = defaultdict(float)

    for w, p in zip(w1_weights, w1_paths):
        vol = w * base
        path_bytes[p] += vol
        path_base[p] += vol

    for w, p in zip(w2_weights, w2_paths):
        vol = w * overflow
        path_bytes[p] += vol
        path_over[p] += vol

    B_st = sum(path_bytes.values())

    # Build per-path flows
    flows = []
    for pidx in sorted(path_bytes.keys()):
        vol = path_bytes[pidx]
        if vol <= 0:
            continue
        flows.append({
            "src":        src,
            "dst":        dst,
            "size":       int(round(vol)),
            "path_idx":   pidx,
            "rate_mbps":  rate_mbps,
            "start_ps":   start_ps,
            "base_bytes": path_base[pidx],
            "over_bytes": path_over[pidx],
        })

    return flows, D_st, B_st, base, overflow


# ---------------------------------------------------------------------------
# TM file writer
# ---------------------------------------------------------------------------

def write_tm(outfile, nodes, all_flows, pair_summaries):
    """Write htsim-compatible .tm file."""

    total_conns = len(all_flows)
    lines = []
    lines.append("# Auto-generated TM by generate_te_tm.py")
    lines.append("# Threshold-based demand/admitted split")
    lines.append(f"# Pairs: {len(pair_summaries)}, Sub-flows: {total_conns}")

    # Pair summary comments
    for ps in pair_summaries:
        lines.append(f"# Pair {ps['src']}->{ps['dst']}:  "
                      f"D_st={ps['D_st']:.0f}  T={ps['T']:.0f}  "
                      f"base={ps['base']:.0f}  overflow={ps['overflow']:.0f}  "
                      f"B_st={ps['B_st']:.0f}  "
                      f"sum(W1)={ps['sum_W1']:.4f}  sum(W2)={ps['sum_W2']:.4f}")

    lines.append(f"Nodes {nodes}")
    lines.append(f"Connections {total_conns}")

    flow_id = 0
    processed_pairs = set()

    for f in all_flows:
        flow_id += 1
        pair_key = (f["src"], f["dst"])

        tokens = [
            f'{f["src"]}->{f["dst"]}',
            f'id {flow_id}',
            f'start {f["start_ps"]}',
            f'size {f["size"]}',
            f'paths_idx {f["path_idx"]}',
        ]

        # Per-flow rate override
        if f["rate_mbps"] > 0:
            tokens.append(f'rate {f["rate_mbps"]}')

        # Attach pair-level demand/admitted to the FIRST sub-flow of each pair.
        # This way the simulator's per-pair aggregation sums correctly.
        if pair_key not in processed_pairs:
            ps = next(p for p in pair_summaries
                      if p["src"] == f["src"] and p["dst"] == f["dst"])
            tokens.append(f'demand {int(round(ps["D_st"]))}')
            tokens.append(f'admitted {int(round(ps["B_st"]))}')
            processed_pairs.add(pair_key)

        lines.append(" ".join(tokens))

    with open(outfile, "w") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_json_config(path):
    with open(path) as fh:
        return json.load(fh)


def build_from_config(cfg):
    """Process a full JSON config and return (nodes, all_flows, pair_summaries)."""

    nodes          = cfg["nodes"]
    global_thresh  = float(cfg.get("threshold", 0))
    global_rate    = float(cfg.get("default_rate_mbps", 0))
    global_start   = cfg.get("start_time_ps", 0)

    all_flows = []
    pair_summaries = []

    for pcfg in cfg["pairs"]:
        flows, D_st, B_st, base, overflow = compute_pair_flows(
            pcfg, global_thresh, global_rate, global_start
        )

        w1_cfg = pcfg.get("W1", {})
        w2_cfg = pcfg.get("W2", {})
        sum_w1 = sum(w1_cfg.get("weights", []))
        sum_w2 = sum(w2_cfg.get("weights", []))
        T = float(pcfg.get("threshold", global_thresh))

        pair_summaries.append({
            "src": pcfg["src"],
            "dst": pcfg["dst"],
            "D_st": D_st,
            "T": T,
            "B_st": B_st,
            "base": base,
            "overflow": overflow,
            "sum_W1": sum_w1,
            "sum_W2": sum_w2,
        })
        all_flows.extend(flows)

    return nodes, all_flows, pair_summaries


def build_from_cli(args):
    """Build config from flat CLI arguments (single-pair convenience mode)."""

    w1_weights = [float(x) for x in args.W1.split(",")]
    w2_weights = [float(x) for x in args.W2.split(",")] if args.W2 else []
    w1_paths   = [int(x) for x in args.W1_paths.split(",")]
    w2_paths   = ([int(x) for x in args.W2_paths.split(",")]
                  if args.W2_paths else list(range(len(w2_weights))))

    cfg = {
        "nodes": args.nodes,
        "threshold": args.threshold,
        "default_rate_mbps": args.rate,
        "start_time_ps": args.start,
        "pairs": [{
            "src": args.src,
            "dst": args.dst,
            "D_st": args.D_st,
            "W1": {"weights": w1_weights, "path_indices": w1_paths},
            "W2": {"weights": w2_weights, "path_indices": w2_paths},
        }],
    }
    return build_from_config(cfg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate threshold-based TE traffic matrix for htsim",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # JSON config mode
    parser.add_argument("--config", help="JSON config file path")
    parser.add_argument("--output", "-o", default="out.tm",
                        help="Output .tm file (default: out.tm)")

    # CLI single-pair mode
    parser.add_argument("--nodes", type=int, default=0)
    parser.add_argument("--src", type=int, default=-1)
    parser.add_argument("--dst", type=int, default=-1)
    parser.add_argument("--D_st", type=float, default=0,
                        help="Total demand for the pair (bytes)")
    parser.add_argument("--threshold", "-T", type=float, default=0,
                        help="Volume threshold (bytes)")
    parser.add_argument("--W1", type=str, default="",
                        help="Base split weights (comma-sep, e.g. 0.6,0.4)")
    parser.add_argument("--W1_paths", type=str, default="",
                        help="Path indices for W1 (comma-sep, e.g. 0,1)")
    parser.add_argument("--W2", type=str, default="",
                        help="Overflow split weights (comma-sep)")
    parser.add_argument("--W2_paths", type=str, default="",
                        help="Path indices for W2 (comma-sep)")
    parser.add_argument("--rate", type=float, default=0,
                        help="Sending rate per sub-flow (Mbps)")
    parser.add_argument("--start", type=float, default=0,
                        help="Start time in picoseconds")

    # Verbosity
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress summary output")

    args = parser.parse_args()

    # Decide mode
    if args.config:
        cfg = load_json_config(args.config)
        nodes, all_flows, pair_summaries = build_from_config(cfg)
    elif args.src >= 0 and args.dst >= 0:
        nodes, all_flows, pair_summaries = build_from_cli(args)
    else:
        parser.print_help()
        sys.exit(1)

    # Write .tm file
    write_tm(args.output, nodes, all_flows, pair_summaries)

    # Print summary
    if not args.quiet:
        total_D = sum(p["D_st"] for p in pair_summaries)
        total_B = sum(p["B_st"] for p in pair_summaries)
        print(f"Generated {args.output}:  {len(all_flows)} flows, "
              f"{len(pair_summaries)} pairs")
        print()
        for ps in pair_summaries:
            print(f"  Pair {ps['src']}->{ps['dst']}:")
            print(f"    D_st      = {ps['D_st']:>14,.0f} bytes")
            print(f"    Threshold = {ps['T']:>14,.0f} bytes")
            print(f"    base      = {ps['base']:>14,.0f} bytes  (min(D_st, T))")
            print(f"    overflow  = {ps['overflow']:>14,.0f} bytes  (max(0, D_st - T))")
            print(f"    B_st      = {ps['B_st']:>14,.0f} bytes  (actual admitted)")
            print(f"    sum(W1)   = {ps['sum_W1']:.4f}")
            print(f"    sum(W2)   = {ps['sum_W2']:.4f}")
            print(f"    B_st/D_st = {ps['B_st']/ps['D_st']:.4f}" if ps['D_st'] > 0 else "")
            print()
        print(f"  Total D_st = {total_D:>14,.0f} bytes")
        print(f"  Total B_st = {total_B:>14,.0f} bytes")
        if total_D > 0:
            print(f"  B/D ratio  = {total_B/total_D:.4f}")
        print()

        # Per-flow detail
        print("  Sub-flow detail:")
        print(f"  {'id':>3}  {'src->dst':>8}  {'path':>4}  {'size':>14}  "
              f"{'base':>14}  {'overflow':>14}  {'rate':>8}")
        for i, f in enumerate(all_flows, 1):
            print(f"  {i:3d}  {f['src']:>3}->{f['dst']:<3}  "
                  f"{f['path_idx']:4d}  {f['size']:14,d}  "
                  f"{f['base_bytes']:14,.0f}  {f['over_bytes']:14,.0f}  "
                  f"{f['rate_mbps']:8.1f}")


if __name__ == "__main__":
    main()
