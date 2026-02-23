#!/bin/bash
set -e

# Directory setup
EXP_DIR="experiments/threshold_vs_fixed"
TOPO="$EXP_DIR/abilene.json"
TM_DIR="$EXP_DIR/tms"
mkdir -p "$EXP_DIR/logs"

# Ensure htsim_cbr updates are built
cd sim/datacenter && make htsim_cbr > /dev/null && cd ../..

echo "Starting Experiment: Threshold vs Fixed Routing"
echo "------------------------------------------------"

for i in {1..5}; do
    echo "Run $i:"
    
    # 1. Fixed Routing
    echo "  Running Fixed Routing..."
    ./sim/datacenter/htsim_cbr -json_topo "$TOPO" -tm "$TM_DIR/fixed_$i.tm" -o "$EXP_DIR/logs/fixed_$i.log" -rate 60 -end 0.2
    
    # 2. Threshold Routing
    echo "  Running Threshold Routing..."
    ./sim/datacenter/htsim_cbr -json_topo "$TOPO" -tm "$TM_DIR/thresh_$i.tm" -o "$EXP_DIR/logs/thresh_$i.log" -rate 60 -end 0.2
done

echo "Experiment complete. Results in $EXP_DIR/logs/"
