# Traffic-engineering demand/admitted example TM
# Each flow specifies:
#   demand  <bytes>  - total application-layer demand (d_st); metadata only
#   admitted <bytes> - solver-admitted volume (b_st); drives CBR generation
#   rate <Mbps>      - (optional) per-flow sending rate; overrides CLI -rate
#
# The simulator generates exactly 'admitted' bytes per flow (split across
# the specified paths/ratios), and measures how many are delivered to the sink.
#
#  8-node fat-tree example: 3 flows, some over-subscribed.

Nodes 8
Connections 3

# Flow 1: 0->7, demand=50MB, admitted=40MB by solver, send at 800 Mbps on 2 paths
0->7 id 1 start 0 demand 50000000 admitted 40000000 rate 800 paths 2 split 0.6,0.4

# Flow 2: 1->6, demand=30MB, only 20MB admitted, default rate, single path
1->6 id 2 start 0 demand 30000000 admitted 20000000

# Flow 3: 2->5, demand=10MB, fully admitted (10MB), 500 Mbps, 2 paths equal split
2->5 id 3 start 0 demand 10000000 admitted 10000000 rate 500 paths 2 split 0.5,0.5
