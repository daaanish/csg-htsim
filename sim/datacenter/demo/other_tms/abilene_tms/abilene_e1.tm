# to be used for demo with the abilene topo (abilene.json)

Nodes 12
Connections 2

# Two flows, same src and dst (r2 -> r11), each using a different path
# No shared paths between the two flows
# Paths are indexed from zero
# [0] q_r2_r6 | q_r6_r7 | q_r7_r4 | q_r4_r11
# [1] q_r2_r5 | q_r5_r8 | q_r8_r10 | q_r10_r11
# [2] q_r2_r5 | q_r5_r7 | q_r7_r4 | q_r4_r11

# Each flow is size 5,000,000 bytes
# Send rate is 1000 Mbps

# 0 based indexing for switches/hosts

1->10 start 0 size 5000000 paths_idx 0
1->10 start 0 size 5000000 paths_idx 1


