"""
Predicted loss model for Experiment 2.

Computes expected per-tunnel loss by propagating surviving volume
hop-by-hop along each tunnel's path.

For each edge, utilization U = total_arriving_load / capacity.
If U > 1, each tunnel's surviving volume is scaled by cap / total_load.
Upstream drops reduce the arriving load at downstream edges.

Usage: called from exp2/run.py — not standalone.
"""

import json
import re
import subprocess
from collections import defaultdict


def load_topology(topo_path):
    """Load topology JSON. Returns {(src, dst): capacity_mbps} for all edges."""
    with open(topo_path) as f:
        topo = json.load(f)

    edges = {}
    for link in topo["links"]:
        src = link["src"]
        dst = link["dst"]
        cap = link["speed_mbps"]
        edges[(src, dst)] = cap
        edges[(dst, src)] = cap
    return edges


def get_path_data(htsim_path, topo_path, src_idx, dst_idx, k=4):
    """Get K-shortest paths as queue-hop strings and edge lists.

    Returns {path_index: {"hops": str, "edges": [(edge_src, edge_dst), ...]}}
    """
    result = subprocess.run(
        [htsim_path, "-json_topo", topo_path,
         "-list_kshort", str(src_idx), str(dst_idx), str(k)],
        capture_output=True, text=True
    )
    output = result.stdout + result.stderr

    paths = {}
    for line in output.splitlines():
        match = re.match(r'\[(\d+)\]\s+(.*)', line)
        if not match:
            continue
        idx = int(match.group(1))
        queue_str = match.group(2)
        edges = []
        for q in queue_str.split("|"):
            q = q.strip()
            parts = re.match(r'q_(\w+)_(\w+)', q)
            if parts:
                edges.append((parts.group(1), parts.group(2)))
        paths[idx] = {"hops": queue_str, "edges": edges}
    return paths


def get_path_edges(htsim_path, topo_path, src_idx, dst_idx, k=4):
    """Backward-compatible wrapper returning only edge lists."""
    return {idx: info["edges"]
            for idx, info in get_path_data(htsim_path, topo_path, src_idx, dst_idx, k).items()}


def get_runtime_path_hops(pairs, topo_path, htsim_path, k=4):
    """Return {(src, dst, path_idx): path_hops_string} for active experiment paths."""
    hops = {}
    cache = {}
    for p in pairs:
        key = (p["src"], p["dst"])
        if key not in cache:
            cache[key] = get_path_data(htsim_path, topo_path, p["src"], p["dst"], k)
        for pidx in p["path_indices"]:
            info = cache[key].get(pidx)
            if info:
                hops[(p["src"], p["dst"], pidx)] = info["hops"]
    return hops


def compute_predicted_loss(pairs, topo_path, htsim_path, sim_end, k=4):
    """Compute predicted per-tunnel loss with cascading edge drops.

    Walk each tunnel hop-by-hop. At each edge, compute arriving load
    from all tunnels, apply (U-1)/U drops, and propagate surviving
    volume to the next hop.

    Returns list of {src, dst, path_idx, input_volume_mbps,
                     pred_delivered_mbps, pred_delivered_bytes,
                     pred_delivered_frac, pred_loss}
    """
    edge_caps = load_topology(topo_path)

    # Step 1: Build tunnel list with edge sequences
    tunnels = []
    all_path_edges = {}

    for p in pairs:
        src, dst = p["src"], p["dst"]
        d_st = float(p["d_st"])
        W = p["W"]
        paths = p["path_indices"]

        key = (src, dst)
        if key not in all_path_edges:
            all_path_edges[key] = get_path_data(htsim_path, topo_path, src, dst, k)

        for k, pidx in enumerate(paths):
            w = W[k] if k < len(W) else 0.0
            volume = w * d_st
            info = all_path_edges[key].get(pidx, {"edges": [], "hops": ""})
            tunnels.append({
                "src": src, "dst": dst, "path_idx": pidx,
                "input_volume": volume,
                "edges": info["edges"],
                "path_hops": info["hops"],
                "surviving": volume,  # will be updated
            })

    # Step 2: Propagate loss hop-by-hop
    #
    # Collect all edges that appear in any tunnel path. For each edge,
    # compute the arriving load (sum of surviving volumes from all
    # tunnels at that edge position). Then apply drop if congested
    # and reduce surviving volumes for downstream edges.
    #
    # We process edges by walking each tunnel's path in order.
    # For each hop position (0, 1, 2, ...):
    #   - Sum surviving volumes for that edge from all tunnels
    #   - Apply drop fraction if congested
    #   - Update surviving volumes for subsequent hops

    # Find max path length
    max_hops = max((len(t["edges"]) for t in tunnels), default=0)

    # Per-tunnel surviving volume tracks what reaches each hop
    surviving = [t["input_volume"] for t in tunnels]

    edge_utilizations = {}  # for debug output

    for hop in range(max_hops):
        # Group tunnels by which edge they traverse at this hop
        edge_load = {}  # edge -> total arriving load
        edge_tunnels = {}  # edge -> list of tunnel indices

        for i, t in enumerate(tunnels):
            if hop >= len(t["edges"]):
                continue
            edge = t["edges"][hop]
            edge_load[edge] = edge_load.get(edge, 0) + surviving[i]
            if edge not in edge_tunnels:
                edge_tunnels[edge] = []
            edge_tunnels[edge].append(i)

        # Apply drops at congested edges
        for edge, load in edge_load.items():
            cap = edge_caps.get(edge, float('inf'))
            U = load / cap if cap > 0 else float('inf')

            # Record for debug
            if edge not in edge_utilizations or U > edge_utilizations[edge]["U"]:
                edge_utilizations[edge] = {"load": load, "cap": cap, "U": U}

            if U > 1:
                # Each tunnel loses proportionally
                scale = cap / load  # = 1/U
                for idx in edge_tunnels[edge]:
                    surviving[idx] *= scale

    # Step 3: Build predictions
    predictions = []
    for i, t in enumerate(tunnels):
        delivered_frac = surviving[i] / t["input_volume"] if t["input_volume"] > 0 else 1.0
        delivered_mbps = surviving[i]
        predictions.append({
            "src": t["src"], "dst": t["dst"],
            "path_idx": t["path_idx"],
            "path_hops": t["path_hops"],
            "input_volume_mbps": t["input_volume"],
            "pred_delivered_mbps": delivered_mbps,
            "pred_delivered_bytes": delivered_mbps * sim_end * 1e6 / 8.0,
            "pred_delivered_frac": delivered_frac,
            "pred_loss": 1.0 - delivered_frac,
        })

    # Print edge utilizations
    print(f"\n  Edge Utilizations (arriving load after upstream drops):")
    for edge in sorted(edge_utilizations.keys()):
        info = edge_utilizations[edge]
        flag = " *** CONGESTED" if info["U"] > 1 else ""
        print(f"    {edge[0]}->{edge[1]}: "
              f"load={info['load']:.1f} cap={info['cap']} "
              f"U={info['U']:.2f}{flag}")

    return predictions


def aggregate_predictions_by_pair(predictions):
    """Aggregate predicted tunnel delivery to per-pair totals."""
    pairs = defaultdict(lambda: {
        "input_mbps": 0.0,
        "pred_delivered_mbps": 0.0,
        "pred_delivered_bytes": 0.0,
    })
    for pred in predictions:
        key = (pred["src"], pred["dst"])
        pairs[key]["input_mbps"] += pred["input_volume_mbps"]
        pairs[key]["pred_delivered_mbps"] += pred["pred_delivered_mbps"]
        pairs[key]["pred_delivered_bytes"] += pred["pred_delivered_bytes"]

    out = []
    for (src, dst), vals in sorted(pairs.items()):
        pred_loss = (1.0 - vals["pred_delivered_mbps"] / vals["input_mbps"]
                     if vals["input_mbps"] > 0 else 0.0)
        out.append({
            "src": src,
            "dst": dst,
            "input_mbps": vals["input_mbps"],
            "pred_delivered_mbps": vals["pred_delivered_mbps"],
            "pred_delivered_bytes": vals["pred_delivered_bytes"],
            "pred_loss": pred_loss,
        })
    return out


def print_comparison(predictions, actual_tunnels, sim_end):
    """Print predicted vs actual effective flow and loss side by side."""
    print(f"\n{'='*70}")
    print(f"  Predicted (math) vs Actual (htsim) Per-Tunnel Delivery")
    print(f"{'='*70}")
    print(f"  {'src':>4}->{'dst':<4} {'path':>5}  {'input':>8} {'pred_eff':>9} {'actual_eff':>11}  {'pred_loss':>9} {'actual_loss':>11}")
    print(f"  {'-'*9} {'-'*5}  {'-'*8} {'-'*9} {'-'*11}  {'-'*9} {'-'*11}")

    for pred in predictions:
        actual = next(
            (a for a in actual_tunnels
             if a["src"] == pred["src"] and a["dst"] == pred["dst"]
             and a["path_idx"] == pred["path_idx"]),
            None
        )
        actual_loss = actual["loss_ratio"] if actual else 0
        actual_eff = (actual["total_delivered"] * 8 / (sim_end * 1e6)) if actual else 0.0
        print(f"  {pred['src']:>4}->{pred['dst']:<4} {pred['path_idx']:>5}  "
              f"{pred['input_volume_mbps']:>7.2f} "
              f"{pred['pred_delivered_mbps']:>8.2f} "
              f"{actual_eff:>10.2f}  "
              f"{pred['pred_loss']:>8.2%} {actual_loss:>10.2%}")


def print_pair_comparison(pair_predictions, actual_pairs, sim_end):
    """Print predicted vs actual per-pair effective flow."""
    print(f"\n{'='*70}")
    print(f"  Predicted (math) vs Actual (htsim) Per-Pair Delivery")
    print(f"{'='*70}")
    print(f"  {'src':>4}->{'dst':<4}  {'input':>8} {'pred_eff':>9} {'actual_eff':>11}  {'pred_loss':>9} {'actual_loss':>11}")
    print(f"  {'-'*9}  {'-'*8} {'-'*9} {'-'*11}  {'-'*9} {'-'*11}")

    for pred in pair_predictions:
        actual = actual_pairs.get((pred["src"], pred["dst"]))
        actual_delivered = actual["delivered"] if actual else 0
        actual_sent = actual["sent"] if actual else 0
        actual_eff = actual_delivered * 8 / (sim_end * 1e6) if actual else 0.0
        actual_loss = ((actual_sent - actual_delivered) / actual_sent
                       if actual and actual_sent > 0 else 0.0)
        print(f"  {pred['src']:>4}->{pred['dst']:<4}  "
              f"{pred['input_mbps']:>7.2f} "
              f"{pred['pred_delivered_mbps']:>8.2f} "
              f"{actual_eff:>10.2f}  "
              f"{pred['pred_loss']:>8.2%} {actual_loss:>10.2%}")
