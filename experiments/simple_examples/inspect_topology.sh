#!/usr/bin/env bash
# HTSIM Topology Inspector
# Shows the actual topology parameters that HTSIM creates

if [ $# -lt 1 ]; then
    echo "Usage: $0 <topology_file.topo> [optional_args...]"
    echo "Example: $0 timing_test.topo"
    echo "Example: $0 timing_test.topo -linkspeed 1000"
    echo ""
    echo "This shows exactly what topology HTSIM creates from your .topo file"
    exit 1
fi

TOPO_FILE="$1"
shift  # Remove first argument, keep the rest

if [ ! -f "$TOPO_FILE" ]; then
    echo "Error: Topology file '$TOPO_FILE' not found"
    exit 1
fi

echo "=== HTSIM Topology Inspector ==="
echo "Analyzing: $(basename $TOPO_FILE)"
echo ""

# Create minimal traffic matrix for testing
cat > /tmp/inspect_tm.tm << EOF
Nodes 2
Connections 1
Triggers 0  
Failures 0

0 1 0 1000000
EOF

# Get the current directory
CURRENT_DIR=$(pwd)

# Check if we're in sim/datacenter, if not try to find it
if [ ! -f "htsim_ndp" ]; then
    if [ -f "sim/datacenter/htsim_ndp" ]; then
        cd sim/datacenter
    elif [ -f "../../sim/datacenter/htsim_ndp" ]; then
        cd ../../sim/datacenter
        TOPO_FILE="../../$TOPO_FILE"
    else
        echo "Error: Cannot find htsim_ndp executable"
        echo "Please run this script from HTSIM root directory or sim/datacenter/"
        exit 1
    fi
fi

echo "=== Topology Creation Output ==="
# Run HTSIM with minimal simulation to see topology creation
./htsim_ndp -topo "$TOPO_FILE" -tm /tmp/inspect_tm.tm -strat single -end 1 "$@" 2>&1 | \
    grep -E "(No of|Hosts per|switches per|QueueSize|Topology load|nodes created|Fat Tree topology)" | \
    head -20

echo ""
echo "=== Summary ==="
echo "The output above shows the ACTUAL topology that HTSIM created."
echo "Key lines to look for:"
echo "  - 'No of pods': Number of pods created"  
echo "  - 'ToR switches per pod': ToR switches in each pod"
echo "  - 'Agg switches per pod': Aggregation switches in each pod"
echo "  - 'No of core switches': Core layer switches (0 for 2-tier)"
echo "  - 'nodes created': Final number of host nodes"
echo ""
echo "=== Connectivity Analysis ==="

# Extract key values from the output
OUTPUT=$(./htsim_ndp -topo "$TOPO_FILE" -tm /tmp/inspect_tm.tm -strat single -end 1 "$@" 2>&1)

NODES=$(echo "$OUTPUT" | grep "No of nodes:" | awk '{print $4}')
PODS=$(echo "$OUTPUT" | grep "No of pods:" | awk '{print $4}') 
TOR_PER_POD=$(echo "$OUTPUT" | grep "ToR switches per pod:" | awk '{print $5}')
AGG_PER_POD=$(echo "$OUTPUT" | grep "Agg switches per pod:" | awk '{print $5}')
CORE_SWITCHES=$(echo "$OUTPUT" | grep "No of core switches:" | awk '{print $5}')

if [ -n "$NODES" ] && [ -n "$PODS" ] && [ -n "$TOR_PER_POD" ] && [ -n "$AGG_PER_POD" ]; then
    TOTAL_TOR=$((PODS * TOR_PER_POD))
    TOTAL_AGG=$((PODS * AGG_PER_POD))
    
    echo "Actual Network Structure:"
    echo "  Total Hosts: $NODES"
    echo "  Total ToR Switches: $TOTAL_TOR"  
    echo "  Total Aggregation Switches: $TOTAL_AGG"
    echo "  Total Core Switches: ${CORE_SWITCHES:-0}"
    echo ""
    echo "Connectivity Pattern:"
    if [ "$CORE_SWITCHES" = "0" ]; then
        echo "  2-Tier Leaf-Spine:"
        echo "    - Each ToR connects to ALL $TOTAL_AGG aggregation switches"
        echo "    - Each Agg switch connects to ALL $TOTAL_TOR ToR switches"
        echo "    - Full mesh between ToR and Aggregation layers"
    else
        echo "  3-Tier Fat-Tree:"
        echo "    - ToRs connect to Agg switches within same pod"
        echo "    - Agg switches connect to subset of Core switches"
        echo "    - Structured fat-tree connectivity"
    fi
fi

# Clean up
rm -f /tmp/inspect_tm.tm
cd "$CURRENT_DIR"