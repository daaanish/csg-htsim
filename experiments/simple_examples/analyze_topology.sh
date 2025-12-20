#!/usr/bin/env bash
# Complete topology analysis for any HTSIM configuration

echo "=== HTSIM Topology Analyzer ==="
echo "This tool helps you understand what topology is being used and how traffic flows."
echo ""

if [ $# -eq 0 ]; then
    echo "Usage examples:"
    echo ""
    echo "# Analyze built-in topologies:"
    echo "./analyze_topology.sh -nodes 8 -tiers 2"
    echo "./analyze_topology.sh -nodes 18 -tiers 3"
    echo ""
    echo "# Analyze custom topology:"
    echo "./analyze_topology.sh -nodes 4 -topo ../../experiments/simple_examples/topos/simple_4host.topo"
    echo ""
    echo "# Trace specific flows:"
    echo "./trace_flow_path.sh 0 4 -nodes 8 -tiers 2"
    echo "./trace_flow_path.sh 0 1 -nodes 8 -tiers 2"
    echo ""
    exit 0
fi

# Extract parameters
NODES=8
TOPO_FILE=""
ORIGINAL_ARGS=("$@")

while [[ $# -gt 0 ]]; do
    case $1 in
        -nodes)
            NODES="$2"
            shift 2
            ;;
        -topo)
            TOPO_FILE="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Run the appropriate topology visualizer
echo "1. TOPOLOGY STRUCTURE:"
echo "======================"

if [ -n "$TOPO_FILE" ]; then
    echo "Analyzing custom topology file: $TOPO_FILE"
    echo ""
    $(dirname "$0")/visualize_custom_topology.sh "$TOPO_FILE"
else
    echo "Analyzing built-in topology with parameters: ${ORIGINAL_ARGS[@]}"
    echo ""
    $(dirname "$0")/visualize_topology.sh ./htsim_ndp "${ORIGINAL_ARGS[@]}"
fi

echo "Analyzing different flow types for $NODES-node topology:"
echo ""

# Same-ToR flow
echo "--- Same-ToR Flow (0→1) ---"
$(dirname "$0")/trace_flow_path.sh 0 1 "$@"

echo ""
echo ""

# Cross-ToR flow
if [ $NODES -gt 2 ]; then
    CROSS_DST=$((NODES / 2))
    echo "--- Cross-ToR Flow (0→$CROSS_DST) ---"
    $(dirname "$0")/trace_flow_path.sh 0 $CROSS_DST "$@"
fi

echo ""
echo ""
echo "3. RECOMMENDED EXPERIMENTS:"
echo "==========================="

echo "A. Bandwidth comparison:"
echo "   - Same-ToR: 0→1"
echo "   - Cross-ToR: 0→$((NODES/2))"
echo "   - Expected: Same-ToR should be faster"
echo ""

echo "B. Congestion testing:"
echo "   - Single flow: 0→$((NODES/2))"
echo "   - Competing flows: 0→$((NODES/2)), 1→$((NODES/2+1))"
echo "   - Expected: Throughput drops with competition"
echo ""

if [ $NODES -ge 8 ]; then
    echo "C. Incast scenario:"
    echo "   - Multiple senders to one receiver: 0→7, 1→7, 2→7, 3→7"
    echo "   - Expected: Receive-side bottleneck"
fi

echo ""
echo "4. QUICK TEST COMMANDS:"
echo "======================="

echo "# Run working example:"
echo "./experiments/simple_examples/run_simple_working.sh"
echo ""

echo "# Create custom traffic matrix and test:"
cat << 'EOF'
cat > /tmp/test_flows.txt << EOT
Nodes 8
Connections 2
Triggers 0
Failures 0

0->1 start 0 size 104857600
0->4 start 0 size 104857600
EOT

cd sim/datacenter
./htsim_ndp -nodes 8 -tm /tmp/test_flows.txt -linkspeed 1000 -strat ecmp -paths 2 -end 10000000 -o /tmp/results.log
cd ../..
./sim/parse_output /tmp/results.log -ndp -show
EOF

echo ""