#!/usr/bin/env bash
# Test runner for custom topology

TOPO_FILE="${1:-experiments/simple_examples/topos/test-ipad.topo}"

if [ ! -f "$TOPO_FILE" ]; then
    echo "Error: Topology file '$TOPO_FILE' not found"
    echo "Usage: $0 [topology_file.topo]"
    exit 1
fi

echo "=== Testing Custom Topology: $(basename $TOPO_FILE) ==="
echo ""

# Create a simple traffic matrix for testing
cat > /tmp/custom_test.tm << EOF
Nodes 2
Connections 1
Triggers 0
Failures 0

0 5 0 104857600
EOF

echo "Created test traffic matrix:"
cat /tmp/custom_test.tm
echo ""

echo "Running HTSIM simulation..."
cd sim/datacenter

# Run with custom topology
./htsim_ndp \
    -topo "../../$TOPO_FILE" \
    -tm /tmp/custom_test.tm \
    -linkspeed 1000 \
    -strat ecmp_host \
    -paths 2 \
    -end 5000000 \
    -o /tmp/custom_results.log

if [ $? -eq 0 ]; then
    echo ""
    echo "=== Simulation Results ==="
    ../../sim/parse_output /tmp/custom_results.log -ndp -show
    
    echo ""
    echo "=== Files Created ==="
    echo "- Results: /tmp/custom_results.log"
    echo "- Traffic matrix: /tmp/custom_test.tm"
    echo ""
    echo "=== Analysis Tools ==="
    echo "cd ../.."
    echo "./experiments/simple_examples/visualize_custom_topology.sh $TOPO_FILE"
    echo "./experiments/simple_examples/trace_custom_flow_path.sh 0 5 $TOPO_FILE"
else
    echo "Simulation failed. Check your topology file format."
fi

cd ../..