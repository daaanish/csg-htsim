#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../sim/datacenter"

# Build if needed
make -q htsim_ndp || make htsim_ndp

echo "Running simple 8-node NDP simulation..."

# Use built-in 8-node topology with basic parameters
./htsim_ndp \
  -nodes 8 \
  -tm ../../experiments/simple_examples/tm_8host_2flows.txt \
  -linkspeed 1000 \
  -q 50 \
  -mtu 1500 \
  -tiers 2 \
  -strat ecmp \
  -paths 2 \
  -end 10000000 \
  -o ../../experiments/simple_examples/simple_working_results.log

echo "Simulation complete. Results in experiments/simple_examples/simple_working_results.log"

# Parse results
cd ../..
./sim/parse_output experiments/simple_examples/simple_working_results.log -ndp -show || echo "Check raw log for details"