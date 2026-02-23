#!/usr/bin/env bash
# =========================================================================
#  TE Demand vs Admitted — 2-node, 2-path experiment
# =========================================================================
#
#  Topology:  src ---[path A (200 Mbps)]---> dst
#             src ---[path B (200 Mbps)]---> dst
#
#  Two flows: flow 1 pinned to path A, flow 2 pinned to path B.
#  Each flow gets its own admitted volume (b_st).
#
#  *** CHANGE THESE VARIABLES TO ITERATE ***
# =========================================================================

set -euo pipefail

# --- Tunables (1 unit = 100 MB, matching link capacity of 200 Mbps) ------

D_ST=600000000          # d_st: total demand in bytes (6 units = 600 MB)

# Scenario 1: balanced split
B_ST_A_1=200000000      # b_st for path A (2 units = 200 MB)
B_ST_B_1=200000000      # b_st for path B (2 units = 200 MB)
RATE_A_1=200            # sending rate on path A (Mbps)
RATE_B_1=200            # sending rate on path B (Mbps)

# Scenario 2: unbalanced split
B_ST_A_2=300000000      # b_st for path A (3 units = 300 MB)
B_ST_B_2=100000000      # b_st for path B (1 unit  = 100 MB)
RATE_A_2=300            # sending rate on path A (Mbps) — EXCEEDS 200 Mbps capacity!
RATE_B_2=100            # sending rate on path B (Mbps)

# Simulation
END=20.0                # sim duration (seconds) — long enough for all flows
QSIZE=8                 # queue size in packets (small = easier to see drops)

# --- Paths ----------------------------------------------------------------
HTSIM=../../sim/datacenter/htsim_cbr
TOPO=two_path.json
# Path indices (from -list_paths 0 3):
#   [0] = q_src_B | q_B_dst  (path B)
#   [1] = q_src_A | q_A_dst  (path A)
PATH_A=1
PATH_B=0

# --- Helper: generate TM file --------------------------------------------
gen_tm() {
    local dst_file=$1 d_st=$2 bst_a=$3 bst_b=$4 rate_a=$5 rate_b=$6
    local demand_a=$(( d_st / 2 ))
    local demand_b=$(( d_st - demand_a ))
    cat > "$dst_file" <<EOF
# Auto-generated TM — edit tunables in run.sh instead
Nodes 4
Connections 2
0->3 id 1 start 0 demand ${demand_a} admitted ${bst_a} rate ${rate_a} paths_idx ${PATH_A}
0->3 id 2 start 0 demand ${demand_b} admitted ${bst_b} rate ${rate_b} paths_idx ${PATH_B}
EOF
}

# --- Run ------------------------------------------------------------------
echo "Topology: src --[A 200Mbps]--> dst,  src --[B 200Mbps]--> dst"
echo "Total demand (d_st): $D_ST bytes"
echo ""

echo "=============================================="
echo " Scenario 1: Balanced (b_st = $B_ST_A_1 on A, $B_ST_B_1 on B)"
echo "   rates: ${RATE_A_1} Mbps on A, ${RATE_B_1} Mbps on B"
echo "=============================================="
gen_tm scenario_1.tm "$D_ST" "$B_ST_A_1" "$B_ST_B_1" "$RATE_A_1" "$RATE_B_1"
echo ""; cat scenario_1.tm; echo ""
$HTSIM -json_topo "$TOPO" -tm scenario_1.tm -end "$END" -q "$QSIZE" -o scenario_1.dat 2>&1 \
    | grep -E '(Flow |FLOW_STATS|PAIR_STATS|GLOBAL_STATS|Total flows)'
echo ""

echo "=============================================="
echo " Scenario 2: Unbalanced (b_st = $B_ST_A_2 on A, $B_ST_B_2 on B)"
echo "   rates: ${RATE_A_2} Mbps on A, ${RATE_B_2} Mbps on B"
echo "=============================================="
gen_tm scenario_2.tm "$D_ST" "$B_ST_A_2" "$B_ST_B_2" "$RATE_A_2" "$RATE_B_2"
echo ""; cat scenario_2.tm; echo ""
$HTSIM -json_topo "$TOPO" -tm scenario_2.tm -end "$END" -q "$QSIZE" -o scenario_2.dat 2>&1 \
    | grep -E '(Flow |FLOW_STATS|PAIR_STATS|GLOBAL_STATS|Total flows)'
echo ""

echo "=============================================="

echo "To iterate: edit the B_ST and RATE variables at the top of run.sh"
