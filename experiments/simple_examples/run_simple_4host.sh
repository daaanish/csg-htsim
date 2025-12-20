#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../sim/datacenter"

# Build if needed
make -q htsim_ndp || make htsim_ndp

echo "Running 4-host, 2-flow NDP simulation..."

# Run simulation with ECMP strategy instead of single path
./htsim_ndp \
  -nodes 4 \
  -tm ../../experiments/simple_examples/tm_4host_2flows.txt \
  -linkspeed 1000 \
  -q 50 \
  -mtu 1500 \
  -tiers 2 \
  -strat ecmp \
  -paths 1 \
  -end 20000000 \
  -o ../../experiments/simple_examples/simple_4host_results.log

echo "Simulation complete. Results in experiments/simple_examples/simple_4host_results.log"

# Parse results
cd ../..
./sim/parse_output experiments/simple_examples/simple_4host_results.log -ndp -show || echo "Parse failed, check raw log"