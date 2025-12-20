#!/usr/bin/env bash
# Compare Same-ToR vs Cross-ToR Flow Times
# Uses your test-ipad.topo topology for real timing comparison

TOPO_FILE="${1:-experiments/simple_examples/topos/test-ipad.topo}"

if [ ! -f "$TOPO_FILE" ]; then
    echo "Error: Topology file '$TOPO_FILE' not found"
    echo "Usage: $0 [topology_file.topo]"
    exit 1
fi

echo "=== Same-ToR vs Cross-ToR Timing Comparison ==="
echo "Topology: $(basename $TOPO_FILE)"
echo ""

# First, analyze the topology to understand the setup
echo "=== Topology Analysis ==="
./experiments/simple_examples/verify_htsim_routing.sh 0 3 "$TOPO_FILE" | head -15
echo ""

echo "=== Test Configuration ==="
echo "Same-ToR flow: Host 0 → Host 3 (both on ToR-0)"
echo "Cross-ToR flow: Host 0 → Host 5 (ToR-0 → ToR-1)"
echo "Flow size: 100MB (to get measurable completion times)"
echo ""

# Create traffic matrix for same-ToR flow
cat > /tmp/same_tor_test.tm << EOF
Nodes 2
Connections 1
Triggers 0
Failures 0

0 3 0 104857600
EOF

# Create traffic matrix for cross-ToR flow
cat > /tmp/cross_tor_test.tm << EOF
Nodes 2
Connections 1
Triggers 0
Failures 0

0 5 0 104857600
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
    -end 50000000 \
    -o /tmp/same_tor_results.log > /tmp/same_tor_output.txt 2>&1

if [ $? -eq 0 ]; then
    echo "✓ Same-ToR test completed"
    
    # Parse completion time
    SAME_TOR_TIME=$(../../sim/parse_output /tmp/same_tor_results.log -ndp -completion | grep -o "[0-9.]*us" | head -1)
    if [ -n "$SAME_TOR_TIME" ]; then
        echo "Same-ToR completion time: $SAME_TOR_TIME"
    else
        echo "Checking raw results for timing..."
        ../../sim/parse_output /tmp/same_tor_results.log -ndp -show | head -10
    fi
else
    echo "✗ Same-ToR test failed"
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
    -end 50000000 \
    -o /tmp/cross_tor_results.log > /tmp/cross_tor_output.txt 2>&1

if [ $? -eq 0 ]; then
    echo "✓ Cross-ToR test completed"
    
    # Parse completion time
    CROSS_TOR_TIME=$(../../sim/parse_output /tmp/cross_tor_results.log -ndp -completion | grep -o "[0-9.]*us" | head -1)
    if [ -n "$CROSS_TOR_TIME" ]; then
        echo "Cross-ToR completion time: $CROSS_TOR_TIME"
    else
        echo "Checking raw results for timing..."
        ../../sim/parse_output /tmp/cross_tor_results.log -ndp -show | head -10
    fi
else
    echo "✗ Cross-ToR test failed"
    cat /tmp/cross_tor_output.txt
fi

cd ../..

echo ""
echo "=== Timing Comparison Results ==="

if [ -n "$SAME_TOR_TIME" ] && [ -n "$CROSS_TOR_TIME" ]; then
    echo "Same-ToR (0→3):  $SAME_TOR_TIME"
    echo "Cross-ToR (0→5): $CROSS_TOR_TIME"
    echo ""
    
    # Extract numeric values for calculation
    SAME_NUM=$(echo "$SAME_TOR_TIME" | grep -o "[0-9.]*")
    CROSS_NUM=$(echo "$CROSS_TOR_TIME" | grep -o "[0-9.]*")
    
    if [ -n "$SAME_NUM" ] && [ -n "$CROSS_NUM" ]; then
        RATIO=$(echo "scale=2; $CROSS_NUM / $SAME_NUM" | bc -l)
        DIFF=$(echo "scale=2; $CROSS_NUM - $SAME_NUM" | bc -l)
        
        echo "Performance Analysis:"
        echo "  Cross-ToR is ${RATIO}x slower than Same-ToR"
        echo "  Difference: ${DIFF}us"
        echo ""
        
        if (( $(echo "$RATIO > 1.5" | bc -l) )); then
            echo "✓ Significant performance difference detected!"
            echo "  Cross-ToR flows are much slower due to 4-hop path"
        else
            echo "⚠ Small difference - may need larger flows or lower bandwidth"
        fi
    fi
else
    echo "Manual comparison needed - check the detailed results:"
    echo ""
    echo "Same-ToR detailed results:"
    ../../sim/parse_output /tmp/same_tor_results.log -ndp -show 2>/dev/null | head -5
    echo ""
    echo "Cross-ToR detailed results:"
    ../../sim/parse_output /tmp/cross_tor_results.log -ndp -show 2>/dev/null | head -5
fi

echo ""
echo "=== Detailed Analysis ==="
echo "Why Cross-ToR is slower:"
echo "  1. More hops: 4 vs 2 (2x more switch/link latency)"
echo "  2. Uplink bottleneck: ToR uplinks shared among hosts"
echo "  3. Queue delays: More queues = more queuing delay"
echo ""
echo "Your topology uplink configuration:"
grep -A 10 "^tier 0" "$TOPO_FILE" | grep -E "(radix_up|radix_down|oversubscribed)"

echo ""
echo "=== Files Created ==="
echo "  Same-ToR results: /tmp/same_tor_results.log"
echo "  Cross-ToR results: /tmp/cross_tor_results.log"
echo "  Same-ToR output: /tmp/same_tor_output.txt"
echo "  Cross-ToR output: /tmp/cross_tor_output.txt"