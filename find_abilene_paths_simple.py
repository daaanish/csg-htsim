import json
import sys

def find_paths(graph, start, end, path=[]):
    path = path + [start]
    if start == end:
        return [path]
    if start not in graph:
        return []
    paths = []
    for node in graph[start]:
        if node not in path:
            newpaths = find_paths(graph, node, end, path)
            for newpath in newpaths:
                paths.append(newpath)
    return paths

def main():
    try:
        with open('experiments/threshold_vs_fixed/abilene.json') as f:
            topo = json.load(f)
    except FileNotFoundError:
        print("Error: experiments/threshold_vs_fixed/abilene.json not found")
        sys.exit(1)

    adj = {}
    for link in topo['links']:
        s, d = link['src'], link['dst']
        if s not in adj: adj[s] = []
        if d not in adj: adj[d] = []
        adj[s].append(d)
        if link.get('bidirectional', True):
            adj[d].append(s)

    src = "r1"
    dst = "r11"
    
    print(f"Finding paths from {src} to {dst}...")
    all_paths = find_paths(adj, src, dst)
    all_paths.sort(key=len)
    
    print(f"Found {len(all_paths)} paths:")
    for i, p in enumerate(all_paths):
        print(f"Path {i}: {' -> '.join(p)} (Length: {len(p)})")

if __name__ == "__main__":
    main()
