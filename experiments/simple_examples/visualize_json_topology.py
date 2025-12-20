#!/usr/bin/env python3
"""
Visualize a JSON topology using NetworkX and Matplotlib.

JSON format expected (matches htsim JsonTopology):
{
  "hosts": ["h0", "h1", ...],
  "links": [
     {"src":"h0", "dst":"h1", "speed_mbps":1000, "latency_us":1},
     {"src":"h1", "dst":"h2", "speed_gbps":10,  "latency_us":1}
  ]
}

Notes:
- Links are treated as undirected for visualization (htsim makes them bidi internally).
- Edge labels show speed and latency if provided.

Usage:
  python3 visualize_json_topology.py path/to/topology.json \
      -o topo.png --layout spring --labels

Layouts: spring (default), circular, kamada, shell, planar
"""
import argparse
import json
import sys

try:
    # Prefer non-interactive backend for headless servers
    import matplotlib
    if not matplotlib.get_backend().lower().startswith("agg"):
        try:
            matplotlib.use("Agg")
        except Exception:
            pass
    import networkx as nx
    import matplotlib.pyplot as plt
except Exception as e:
    sys.stderr.write("This script requires networkx and matplotlib. Install them with:\n"
                     "  pip install networkx matplotlib\n")
    raise


def parse_args():
    p = argparse.ArgumentParser(description="Visualize JSON topology with NetworkX")
    p.add_argument("json_topo", help="Path to JSON topology file")
    p.add_argument("-o", "--output", help="Output image file (PNG, SVG, PDF). If omitted, shows a window.")
    p.add_argument("--layout", default="spring",
                   choices=["spring", "circular", "kamada", "shell", "planar", "custom"],
                   help="Graph layout algorithm (add 'custom' for hosts on sides, routers in center)")
    p.add_argument("--labels", action="store_true", help="Show node and edge labels")
    p.add_argument("--title", default=None, help="Optional title for the plot")
    return p.parse_args()


def load_topology(path):
    with open(path, "r") as f:
        data = json.load(f)
    hosts = data.get("hosts", [])
    links = data.get("links", [])
    return hosts, links


def build_graph(hosts, links):
    # Undirected representation for visualization
    G = nx.Graph()
    # Add nodes with index attribute for reference
    for idx, h in enumerate(hosts):
        G.add_node(h, index=idx)

    def speed_str(link):
        if "speed_gbps" in link:
            return f"{link['speed_gbps']}Gbps"
        if "speed_mbps" in link:
            return f"{link['speed_mbps']}Mbps"
        return ""

    def lat_str(link):
        for key in ("latency_us", "latency_ms", "latency_ns", "latency_ps"):
            if key in link:
                unit = key.split("_")[1]
                return f"{link[key]}{unit}"
        return ""

    # Add edges once (undirected). If both directions appear, dedup with frozenset
    seen = set()
    for l in links:
        src = l.get("src")
        dst = l.get("dst")
        if src is None or dst is None:
            continue
        key = frozenset((src, dst))
        if key in seen:
            continue
        seen.add(key)
        label = ", ".join(x for x in (speed_str(l), lat_str(l)) if x)
        G.add_edge(src, dst, label=label)
    return G


def compute_layout(G, layout):
    if layout == "spring":
        return nx.spring_layout(G, seed=42)
    if layout == "circular":
        return nx.circular_layout(G)
    if layout == "kamada":
        return nx.kamada_kawai_layout(G)
    if layout == "shell":
        return nx.shell_layout(G)
    if layout == "planar":
        try:
            return nx.planar_layout(G)
        except nx.NetworkXException:
            # Fallback if not planar
            return nx.spring_layout(G, seed=42)
    if layout == "custom":
        # Custom layout: hosts on sides, routers in center
        hosts = [n for n in G.nodes if n.startswith('h')]
        routers = [n for n in G.nodes if n.startswith('r')]
        n_hosts = len(hosts)
        n_routers = len(routers)
        pos = {}
        # Place hosts: half on left, half on right
        hosts_sorted = sorted(hosts)
        half = (n_hosts + 1) // 2
        for i, h in enumerate(hosts_sorted):
            if i < half:
                # Left side
                pos[h] = (-1.5, 1 - 2*i/(half-1) if half>1 else 0)
            else:
                # Right side
                pos[h] = (1.5, 1 - 2*(i-half)/(n_hosts-half-1) if n_hosts-half>1 else 0)
        # Place routers in a row in the center
        routers_sorted = sorted(routers)
        for j, r in enumerate(routers_sorted):
            pos[r] = (0, 1 - 2*j/(n_routers-1) if n_routers>1 else 0)
        return pos
    return nx.spring_layout(G, seed=42)


def draw_graph(G, pos, show_labels=False, title=None):
    plt.figure(figsize=(8, 6))
    nx.draw_networkx_nodes(G, pos, node_color="#4C78A8", node_size=800, edgecolors="black")
    nx.draw_networkx_edges(G, pos, width=1.8, edge_color="#7A5195")

    if show_labels:
        # Node labels: name (index)
        node_labels = {n: f"{n} ({G.nodes[n]['index']})" for n in G.nodes}
        nx.draw_networkx_labels(G, pos, labels=node_labels, font_size=9)

        # Edge labels
        edge_labels = {(u, v): (G.edges[u, v].get("label") or "") for u, v in G.edges}
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=8)

    plt.axis("off")
    if title:
        plt.title(title)


def main():
    args = parse_args()
    hosts, links = load_topology(args.json_topo)
    if not hosts:
        sys.stderr.write("No hosts found in JSON.\n")
        sys.exit(1)
    G = build_graph(hosts, links)
    pos = compute_layout(G, args.layout)
    ttl = args.title or f"Topology: {len(hosts)} hosts, {G.number_of_edges()} links"
    draw_graph(G, pos, show_labels=args.labels, title=ttl)
    if args.output:
        plt.tight_layout()
        plt.savefig(args.output, dpi=200)
        print(f"Wrote {args.output}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
