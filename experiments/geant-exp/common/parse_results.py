"""
Parse htsim output and .tm file to produce per-tunnel results.

Reads:
  1. htsim stdout (from file or string) → FLOW_STATS lines
  2. The .tm file → maps each flow_id to its (src, dst, paths_idx)

Outputs a list of dicts:
  [{flow_id, src, dst, path_idx, sent, delivered, loss_ratio}, ...]
"""

import re


def parse_tm_file(tm_path):
    """Read a .tm file and return {flow_id: path_idx} mapping."""
    flow_to_path = {}
    with open(tm_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if "->" not in line or "id" not in line:
                continue
            # Extract flow id and paths_idx
            id_match = re.search(r'\bid\s+(\d+)', line)
            path_match = re.search(r'\bpaths_idx\s+(\S+)', line)
            if id_match and path_match:
                fid = int(id_match.group(1))
                pidx = int(path_match.group(1).split(",")[0])  # first path
                flow_to_path[fid] = pidx
    return flow_to_path


def parse_htsim_output(output_text):
    """Parse FLOW_STATS lines from htsim stdout.

    Returns list of {flow_id, src, dst, sent, delivered}.
    """
    results = []
    for line in output_text.splitlines():
        if not line.startswith("FLOW_STATS"):
            continue
        fields = {}
        for token in line.split():
            if "=" in token:
                key, val = token.split("=", 1)
                fields[key] = val
        results.append({
            "flow_id": int(fields["flow"]),
            "src": int(fields["src"]),
            "dst": int(fields["dst"]),
            "sent": int(fields["sent_bytes"]),
            "delivered": int(fields["delivered_bytes"]),
        })
    return results


def build_results(htsim_output, tm_path):
    """Combine htsim output with TM file to get per-tunnel results.

    Returns list of dicts with: flow_id, src, dst, path_idx, sent, delivered, loss_ratio
    """
    flow_to_path = parse_tm_file(tm_path)
    flow_stats = parse_htsim_output(htsim_output)

    results = []
    for fs in flow_stats:
        fid = fs["flow_id"]
        path_idx = flow_to_path.get(fid, -1)
        sent = fs["sent"]
        delivered = fs["delivered"]
        loss = (sent - delivered) / sent if sent > 0 else 0.0

        results.append({
            "flow_id": fid,
            "src": fs["src"],
            "dst": fs["dst"],
            "path_idx": path_idx,
            "sent": sent,
            "delivered": delivered,
            "loss_ratio": loss,
        })
    return results


def aggregate_by_tunnel(results):
    """Aggregate per-flow results into per-tunnel (src, dst, path_idx) totals.

    Returns list of {src, dst, path_idx, num_flows, total_sent, total_delivered, loss_ratio}
    """
    tunnels = {}
    for r in results:
        key = (r["src"], r["dst"], r["path_idx"])
        if key not in tunnels:
            tunnels[key] = {"sent": 0, "delivered": 0, "count": 0}
        tunnels[key]["sent"] += r["sent"]
        tunnels[key]["delivered"] += r["delivered"]
        tunnels[key]["count"] += 1

    out = []
    for (src, dst, pidx), t in sorted(tunnels.items()):
        loss = (t["sent"] - t["delivered"]) / t["sent"] if t["sent"] > 0 else 0
        out.append({
            "src": src, "dst": dst, "path_idx": pidx,
            "num_flows": t["count"],
            "total_sent": t["sent"],
            "total_delivered": t["delivered"],
            "loss_ratio": loss,
        })
    return out


def print_results(results, title="Per-Flow Results"):
    """Pretty-print results table."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    print(f"  {'flow':>5} {'src':>4}->{'dst':<4} {'path':>5} "
          f"{'sent':>12} {'delivered':>12} {'loss%':>8}")
    print(f"  {'-'*5} {'-'*9} {'-'*5} {'-'*12} {'-'*12} {'-'*8}")
    for r in results:
        print(f"  {r['flow_id']:>5} {r['src']:>4}->{r['dst']:<4} {r['path_idx']:>5} "
              f"{r['sent']:>12,} {r['delivered']:>12,} {r['loss_ratio']:>7.2%}")


def print_tunnels(tunnels, title="Per-Tunnel Summary"):
    """Pretty-print tunnel aggregation."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    print(f"  {'src':>4}->{'dst':<4} {'path':>5} {'flows':>6} "
          f"{'sent':>12} {'delivered':>12} {'loss%':>8}")
    print(f"  {'-'*9} {'-'*5} {'-'*6} {'-'*12} {'-'*12} {'-'*8}")
    for t in tunnels:
        print(f"  {t['src']:>4}->{t['dst']:<4} {t['path_idx']:>5} {t['num_flows']:>6} "
              f"{t['total_sent']:>12,} {t['total_delivered']:>12,} {t['loss_ratio']:>7.2%}")
