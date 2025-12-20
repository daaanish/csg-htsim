#!/usr/bin/env bash
# Compare Same-ToR vs Cross-ToR Flow Times - FIXED VERSION
# Uses corrected traffic matrix format

TOPO_FILE="${1:-experiments/simple_examples/topos/timing_test.topo}"

if [ ! -f "$TOPO_FILE" ]; then
    echo "Error: Topology file '$TOPO_FILE' not found"
    echo "Usage: $0 [topology_file.topo]"
    exit 1
fi

echo "=== Same-ToR vs Cross-ToR Timing Comparison ==="
echo "Topology: $(basename $TOPO_FILE)"
echo ""

echo "=== Test Configuration ==="
echo "Same-ToR flow: Host 0 → Host 3 (both on ToR-0)"
echo "Cross-ToR flow: Host 0 → Host 5 (ToR-0 → ToR-1)"
echo "Flow size: 100MB (104857600 bytes)"
echo ""

# Create traffic matrix for same-ToR flow (corrected format)
cat > /tmp/same_tor_test.tm << EOF
Nodes 8
Connections 1
Triggers 0
Failures 0

0->3 start 0 size 104857600
EOF

# Create traffic matrix for cross-ToR flow (corrected format)
cat > /tmp/cross_tor_test.tm << EOF
Nodes 8
Connections 1
Triggers 0
Failures 0

0->5 start 0 size 104857600
EOF

cd sim/datacenter

echo "=== Running Same-ToR Flow Test (0→3) ==="
echo "Expected: Faster completion (2-hop path)"

./htsim_ndp \
    -topo "../../$TOPO_FILE" \
    -tm /tmp/same_tor_test.tm \
    -linkspeed 1000 \
    -strat ecmp_host \
    -paths 1 \
    -end 100000000 \
    -o /tmp/same_tor_results.log > /tmp/same_tor_output.txt 2>&1

if [ $? -eq 0 ]; then
    echo "✓ Same-ToR test completed successfully"
    
    # Parse and show results
    echo "Same-ToR Results:"
    ../../sim/parse_output /tmp/same_tor_results.log -ndp -completion
else
    echo "✗ Same-ToR test failed"
    echo "HTSIM output:"
    cat /tmp/same_tor_output.txt
fi

echo ""
echo "=== Running Cross-ToR Flow Test (0→5) ==="
echo "Expected: Slower completion (4-hop path through aggregation)"

./htsim_ndp \
    -topo "../../$TOPO_FILE" \
    -tm /tmp/cross_tor_test.tm \
    -linkspeed 1000 \
    -strat ecmp_host \
    -paths 1 \
    -end 100000000 \
    -o /tmp/cross_tor_results.log > /tmp/cross_tor_output.txt 2>&1

if [ $? -eq 0 ]; then
    echo "✓ Cross-ToR test completed successfully"
    
    # Parse and show results
    echo "Cross-ToR Results:"
    ../../sim/parse_output /tmp/cross_tor_results.log -ndp -completion
else
    echo "✗ Cross-ToR test failed"
    echo "HTSIM output:"
    cat /tmp/cross_tor_output.txt
fi

cd ../..

echo ""
echo "=== Detailed Flow Completion Analysis ==="
echo "Same-ToR flow (Host 0 → Host 3):"
if [ -f /tmp/same_tor_results.log ]; then
    ./sim/parse_output /tmp/same_tor_results.log -ndp -show | head -5
fi

echo ""
echo "Cross-ToR flow (Host 0 → Host 5):"
if [ -f /tmp/cross_tor_results.log ]; then
    ./sim/parse_output /tmp/cross_tor_results.log -ndp -show | head -5
fi

echo ""
echo "=== Expected Results ==="
echo "If working correctly:"
echo "  • Same-ToR flow should complete faster (2 hops)"
echo "  • Cross-ToR flow should be slower (4 hops + uplink contention)"
echo "  • Time difference shows impact of topology on performance"
echo ""
echo "Topology factors affecting performance:"
echo "  • Link latency: 1000ns per hop"
echo "  • Switch latency: 100ns per switch"
echo "  • Same-ToR: 2 hops, 2 switches = 2000ns + 200ns = 2200ns base latency"
echo "  • Cross-ToR: 4 hops, 3 switches = 4000ns + 300ns = 4300ns base latency"