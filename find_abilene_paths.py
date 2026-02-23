import json
import networkx as nx
import sys
print(f"DEBUG: Python executable: {sys.executable}")

def analyze_abilene():
    with open('experiments/threshold_vs_fixed/abilene.json') as f:
        topo = json.load(f)

    G = nx.Graph() # Undirected for now to find paths
    for link in topo['links']:
        G.add_edge(link['src'], link['dst'])

    # We want a pair with multiple paths
    # Let's check r1 (likely West) to r11 (likely East)
    # Hosts are r1..r12
    
    src = "r1"
    dst = "r11"
    
    print(f"Paths from {src} to {dst}:")
    paths = list(nx.all_simple_paths(G, src, dst))
    for p in paths:
        print(" -> ".join(p))

if __name__ == "__main__":
    try:
        analyze_abilene()
    except Exception as e:
        print(e)
