#!/bin/bash
set -e

DIR="experiments/basics"
TOPO="$DIR/diamond_topo.json"
SPLIT_TM="$DIR/split_traffic.tm"
THRESH_TM="$DIR/threshold_traffic.tm"
LOG_SPLIT="$DIR/split.log"
LOG_THRESH="$DIR/thresh.log"

echo "Running Split Traffic Demo (0.5/0.5)..."
./sim/datacenter/htsim_cbr -json_topo "$TOPO" -tm "$SPLIT_TM" -o "$LOG_SPLIT" -end 0.2
echo "Split traffic log: $LOG_SPLIT"
./sim/parse_output "$LOG_SPLIT" -cbr -show

echo ""
echo "Running Threshold Traffic Demo (switch after 1MB)..."
./sim/datacenter/htsim_cbr -json_topo "$TOPO" -tm "$THRESH_TM" -o "$LOG_THRESH" -end 0.2
echo "Threshold traffic log: $LOG_THRESH"
./sim/parse_output "$LOG_THRESH" -cbr -show
