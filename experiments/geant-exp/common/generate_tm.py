"""
TM Generator for htsim — shared by both experiments.

Takes a list of pair configs and produces a .tm file.
Each pair has: src, dst, d_st (Mbps), T_st (Mbps), W1, W2, path_indices.

Flow decomposition per path k:
  base     = min(d_st, T_st)
  overflow = max(0, d_st - T_st)
  volume_k = W1[k] * base + W2[k] * overflow   (Mbps)
  num_flows_k = round(volume_k / rate)

All flows share a common rate and size.
"""


def compute_flows(pairs, rate_mbps, flow_size_bytes):
    """Convert pair configs into a list of (src, dst, path_idx, num_flows).

    pairs: list of dicts with keys:
        src, dst, d_st, T_st, W1 (list), W2 (list), path_indices (list)

    Returns: (flows, summaries)
        flows: list of {src, dst, path_idx, num_flows}
        summaries: list of {src, dst, d_st, T_st, base, overflow, total_flows}
    """
    all_flows = []
    summaries = []

    for p in pairs:
        src, dst = p["src"], p["dst"]
        d_st = float(p["d_st"])
        T_st = float(p["T_st"])
        W1 = p["W1"]
        W2 = p["W2"]
        paths = p["path_indices"]

        base = min(d_st, T_st)
        overflow = max(0.0, d_st - T_st)
        total = 0

        for k, pidx in enumerate(paths):
            w1 = W1[k] if k < len(W1) else 0.0
            w2 = W2[k] if k < len(W2) else 0.0
            volume = w1 * base + w2 * overflow
            n = round(volume / rate_mbps) if rate_mbps > 0 else 0
            if n > 0:
                all_flows.append({
                    "src": src, "dst": dst,
                    "path_idx": pidx, "num_flows": n,
                })
                total += n

        summaries.append({
            "src": src, "dst": dst,
            "d_st": d_st, "T_st": T_st,
            "base": base, "overflow": overflow,
            "total_flows": total,
            "ideal_flows": d_st / rate_mbps if rate_mbps > 0 else 0,
        })

    return all_flows, summaries


def write_tm(filename, nodes, flows, summaries, rate_mbps, flow_size_bytes):
    """Write a .tm file from computed flows."""
    total_conns = sum(f["num_flows"] for f in flows)

    lines = []
    lines.append(f"# Auto-generated TM — rate={rate_mbps} Mbps, size={flow_size_bytes} bytes")
    for s in summaries:
        lines.append(
            f"# {s['src']}->{s['dst']}: d_st={s['d_st']:.1f} T_st={s['T_st']:.1f} "
            f"flows={s['total_flows']} (ideal={s['ideal_flows']:.2f})"
        )
    lines.append(f"Nodes {nodes}")
    lines.append(f"Connections {total_conns}")

    flow_id = 0
    seen = set()

    for f in flows:
        src, dst, pidx = f["src"], f["dst"], f["path_idx"]
        for _ in range(f["num_flows"]):
            flow_id += 1
            tokens = [
                f"{src}->{dst}",
                f"id {flow_id}",
                "start 0",
                f"size {flow_size_bytes}",
                f"rate {rate_mbps}",
                f"paths_idx {pidx}",
            ]
            # Attach demand/admitted metadata to first flow of each pair
            pair_key = (src, dst)
            if pair_key not in seen:
                s = next(x for x in summaries
                         if x["src"] == src and x["dst"] == dst)
                demand = s["total_flows"] * flow_size_bytes
                tokens.append(f"demand {demand}")
                tokens.append(f"admitted {demand}")
                seen.add(pair_key)
            lines.append(" ".join(tokens))

    with open(filename, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return total_conns


def generate(pairs, rate_mbps, flow_size_bytes, nodes, output_file):
    """One-call convenience: compute flows and write TM file.

    Returns (total_flows, summaries) for printing.
    """
    flows, summaries = compute_flows(pairs, rate_mbps, flow_size_bytes)
    total = write_tm(output_file, nodes, flows, summaries,
                     rate_mbps, flow_size_bytes)
    return total, summaries
