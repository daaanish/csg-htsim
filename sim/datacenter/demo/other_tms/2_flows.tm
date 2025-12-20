# to be used for demo with the ABCD-R1R2R3R4 topo

Nodes 8
Connections 2

# Traffic from h0 to h1 and from h2 to h3, two flows of 5MB each
# using path from h0 to r2 to r4 to h1 (path index 1) 
# Paths were: [0] q_h0_r1 | q_r1_h1 [1] q_h0_r2 | q_r2_r4 | q_r4_h1
# Paths can be seen using ./htsim_cbr -json_topo ./demo/topo/8node.json -list_kshort 0 1 3

0->1 start 0 size 5000000 paths_idx 1
2->3 start 0 size 5000000 paths_idx 1

