# Abilene experiment: two flows using two paths each
# Hosts are zero-based indices into JSON hosts array
# r2 -> r10 (1 -> 9) and r1 -> r9 (0 -> 8)
# Let the sim decide rates; we specify paths and optionally use CLI -split
Nodes 12
Connections 2
1->9 start 0 paths 2 paths_idx 0,1
0->8 start 0 paths 2 paths_idx 0,1
