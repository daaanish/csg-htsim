# to be used for demo with the ABCD-R1R2R3R4 topo (8node.json)

Nodes 8
Connections 4

# Traffic from h0 to h1 and from h2 to h3, two flows of 5MB each for each node,
# this should cause overflow in the queues

0->1 start 0 size 5000000 paths_idx 1
0->1 start 0 size 5000000 paths_idx 1
2->3 start 0 size 5000000 paths_idx 1
2->3 start 0 size 5000000 paths_idx 1


