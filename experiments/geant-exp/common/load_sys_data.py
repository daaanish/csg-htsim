"""
Loader for SYS agent output (W1, W2, T_st) + GEANT traffic matrices.

Parses pkl files from sys_data/ and geant-harp-format/, applies the
two-stage threshold routing model, and generates htsim .tm files.

Data layout:
  - W1 = split_ratios_1_{idx}.pkl  → torch [1, 1848, 1] → reshape [462, 4]
  - W2 = split_ratios_2_{idx}.pkl  → torch [1, 1848, 1] → reshape [462, 4]
  - T_st = T_st_{idx}.pkl          → torch [1, 462, 1]  → reshape [462]
  - TM = t{tm_num}.pkl (numpy)     → shape (462,), demand in Gbps

  462 = 22*21 pairs (row-major, skip self-loops)
  4 = K-shortest paths per pair
  T_st is in Mbps
  TM demands are in Gbps (convert ×1000 → Mbps)

Index mapping:
  sys_data index i → eval TMs  7505 + i*5  through  7509 + i*5
"""

import os
import pickle
import math

import torch

# ── CONSTANTS ──────────────────────────────────────────────────────────────
N_NODES = 22
N_PAIRS = N_NODES * (N_NODES - 1)   # 462
K_PATHS = 4
FIRST_EVAL_TM = 7505   # first eval TM number
TMS_PER_INDEX = 5       # 5 eval TMs per sys_data index

# Default paths (relative to geant-exp/)
_HERE = os.path.dirname(os.path.abspath(__file__))
_GEANT_EXP = os.path.dirname(_HERE)  # experiments/geant-exp/
DEFAULT_SYS_DATA_DIR  = os.path.join(_GEANT_EXP, "sys_data")
DEFAULT_TM_DIR        = os.path.join(_GEANT_EXP, "geant-tms", "geant-harp-format")
DEFAULT_PATHS_FILE    = os.path.join(_GEANT_EXP, "topo", "geant_kshort_paths.txt")


def load_path_hops(paths_file=None):
    """Load precomputed K-shortest path hops from file.

    Returns dict: (src, dst, path_idx) -> "q_r1_r5 | q_r5_r7 | q_r7_r2"
    """
    pf = paths_file or DEFAULT_PATHS_FILE
    hops = {}
    with open(pf) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 3)  # src dst idx hops
            if len(parts) == 4:
                src, dst, idx = int(parts[0]), int(parts[1]), int(parts[2])
                hops[(src, dst, idx)] = parts[3]
    return hops


def pair_index_to_src_dst(idx):
    """Convert flat pair index (0..461) to (src, dst) with 0-indexed nodes."""
    src = idx // (N_NODES - 1)
    rem = idx % (N_NODES - 1)
    dst = rem if rem < src else rem + 1
    return src, dst


def sys_data_to_tm_numbers(sys_idx):
    """Return list of 5 eval TM numbers for a given sys_data index."""
    start = FIRST_EVAL_TM + sys_idx * TMS_PER_INDEX
    return list(range(start, start + TMS_PER_INDEX))


def load_weights(sys_idx, sys_data_dir=None):
    """Load W1, W2, T_st for a given sys_data index.

    Returns:
        w1: numpy [462, 4] — base split weights (sum=1 per row)
        w2: numpy [462, 4] — overflow split weights (sum=1 per row)
        t_st: numpy [462]  — threshold per pair in Mbps
    """
    d = sys_data_dir or DEFAULT_SYS_DATA_DIR

    w1 = torch.load(os.path.join(d, f"split_ratios_1_{sys_idx}.pkl"),
                     weights_only=False, map_location="cpu")
    w2 = torch.load(os.path.join(d, f"split_ratios_2_{sys_idx}.pkl"),
                     weights_only=False, map_location="cpu")
    t_st = torch.load(os.path.join(d, f"T_st_{sys_idx}.pkl"),
                       weights_only=False, map_location="cpu")

    w1 = w1.squeeze().view(N_PAIRS, K_PATHS).numpy()
    w2 = w2.squeeze().view(N_PAIRS, K_PATHS).numpy()
    t_st = t_st.squeeze().numpy()  # [462]

    return w1, w2, t_st


def load_tm(tm_num, tm_dir=None):
    """Load a traffic matrix by number. Returns numpy [462] in Gbps."""
    d = tm_dir or DEFAULT_TM_DIR
    path = os.path.join(d, f"t{tm_num}.pkl")
    with open(path, "rb") as f:
        tm = pickle.load(f)
    return tm  # shape (462,), Gbps


def compute_volumes(w1, w2, t_st, demand_gbps):
    """Apply two-stage threshold routing model.

    Args:
        w1:          [462, 4] base weights
        w2:          [462, 4] overflow weights
        t_st:        [462] thresholds in Mbps
        demand_gbps: [462] demands in Gbps

    Returns:
        list of dicts: [{src, dst, path_idx, volume_mbps}, ...]
        summary: {total_pairs, overflow_pairs, total_volume_mbps}
    """
    demand_mbps = demand_gbps * 1000.0  # Gbps → Mbps

    entries = []
    overflow_count = 0
    total_volume = 0.0

    for i in range(N_PAIRS):
        src, dst = pair_index_to_src_dst(i)
        d = demand_mbps[i]
        t = t_st[i]

        if d <= 0:
            continue

        base = min(d, t)
        overflow = max(0.0, d - t)
        if overflow > 0:
            overflow_count += 1

        for k in range(K_PATHS):
            vol = w1[i, k] * base + w2[i, k] * overflow
            if vol > 0:
                entries.append({
                    "src": src,
                    "dst": dst,
                    "path_idx": k,
                    "volume_mbps": vol,
                })
                total_volume += vol

    summary = {
        "total_pairs": sum(1 for d in demand_mbps if d > 0),
        "overflow_pairs": overflow_count,
        "total_volume_mbps": total_volume,
        "total_demand_mbps": float(demand_mbps.sum()),
    }
    return entries, summary


def write_tm_file(outfile, entries, flow_size_bytes, summary=None):
    """Write htsim-compatible .tm file from volume entries.

    Uses exact-rate mode: 1 CBR flow per (pair, path) entry at the
    computed volume rate in Mbps. This eliminates rounding error
    from discretizing into fixed-rate flows.
    """
    # Filter out near-zero volumes
    active = [e for e in entries if e["volume_mbps"] > 0.01]
    total_flows = len(active)

    lines = []
    lines.append("# Auto-generated from SYS agent data by load_sys_data.py")
    lines.append("# Mode: exact-rate (1 flow per tunnel at computed volume)")
    if summary:
        lines.append(f"# Pairs with demand: {summary['total_pairs']}")
        lines.append(f"# Pairs with overflow (d > T_st): {summary['overflow_pairs']}")
        lines.append(f"# Total demand: {summary['total_demand_mbps']:.1f} Mbps")
        lines.append(f"# Total volume: {summary['total_volume_mbps']:.1f} Mbps")
    lines.append(f"# Flow size: {flow_size_bytes} bytes")
    lines.append(f"# Total flows: {total_flows}")
    lines.append(f"Nodes {N_NODES}")
    lines.append(f"Connections {total_flows}")

    flow_id = 0
    for e in active:
        flow_id += 1
        rate = e["volume_mbps"]
        lines.append(
            f"{e['src']}->{e['dst']} id {flow_id} start 0 "
            f"size {flow_size_bytes} rate {rate:.4f} "
            f"paths_idx {e['path_idx']}"
        )

    with open(outfile, "w") as f:
        f.write("\n".join(lines) + "\n")

    return total_flows, active


def load_and_generate(sys_idx, tm_num, outfile, flow_size_bytes,
                      sys_data_dir=None, tm_dir=None):
    """End-to-end: load sys_data + TM, compute volumes, write .tm file.

    Returns (total_flows, entries, summary).
    """
    w1, w2, t_st = load_weights(sys_idx, sys_data_dir)
    demand = load_tm(tm_num, tm_dir)
    entries, summary = compute_volumes(w1, w2, t_st, demand)
    total_flows, active_entries = write_tm_file(
        outfile, entries, flow_size_bytes, summary
    )
    return total_flows, active_entries, summary

