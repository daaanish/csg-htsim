# Scenario: 3 flows @ 10 Mbps each = 30 Mbps
# Flow size: 2501500 bytes for 2.0s duration
Nodes 22
Connections 3
0->15 id 1 start 0 size 2501500 rate 10 paths_idx 0
0->15 id 2 start 0 size 2501500 rate 10 paths_idx 0
0->15 id 3 start 0 size 2501500 rate 10 paths_idx 0
