#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../sim/datacenter"
# Build if needed
make -q htsim_ndp || make htsim_ndp
# Run: 2 nodes via custom topology, 1 flow via TM, 10 Mbps pacing
./htsim_ndp -nodes 2 -conns 0 \
  -tm ../../experiments/tm_oneflow_2nodes_100Mb.txt \
  -topo ../../experiments/topos/leaf_spine_2hosts_minimal.topo \
  -linkspeed 10 -q 15 -mtu 1500 -tiers 2 -strat single -end 12000000 \
  -o ../../experiments/ndp_oneflow_10mbps_100mb.log

# Optional: parse
cd ../..
./sim/parse_output experiments/ndp_oneflow_10mbps_100mb.log -ndp -show || true
