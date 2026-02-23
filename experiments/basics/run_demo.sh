#!/bin/bash
set -e

DIR="experiments/basics"
TOPO="$DIR/simple_topo.json"
TM="$DIR/simple_traffic.tm"
LOG="$DIR/demo.log"

echo "Running Basic HTSim Demo..."
echo "Topology: $TOPO"
echo "Traffic:  $TM"

# Run HTSim (CBR mode)
# -json_topo: specifies JSON topology file
# -tm: specifies traffic matrix file
# -o: output log file
# -end: simulation end time (seconds)
./sim/datacenter/htsim_cbr -json_topo "$TOPO" -tm "$TM" -o "$LOG" -end 0.1

echo "Simulation complete. Analyzing results..."

# Parse output for throughput
# -cbr: constant bit rate mode
./sim/parse_output "$LOG" -cbr -show

echo "Done. Log file available at $LOG"
