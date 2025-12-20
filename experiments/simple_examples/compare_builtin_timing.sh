#!/usr/bin/env bash
# Compare Same-ToR vs Cross-ToR Flow Times - Using Built-in Topology
# This bypasses custom topology issues and uses HTSIM's built-in fat-tree

echo "=== Same-ToR vs Cross-ToR Timing Comparison ==="
echo "Using HTSIM built-in 2-tier topology with 8 nodes"
echo ""

echo "=== Test Configuration ==="
echo "Built-in topology: -nodes 8 -tiers 2"
echo "Same-ToR flow: Host 0 → Host 1 (both on ToR-0)"
echo "Cross-ToR flow: Host 0 → Host 5 (ToR-0 → ToR-1)"
echo "Flow size: 1GB (1073741824 bytes) - Large enough to show clear difference"
echo ""

# Create traffic matrix for same-ToR flow
cat > /tmp/same_tor_builtin.tm << EOF
Nodes 8
Connections 1
Triggers 0
Failures 0

0->1 start 0 size 1073741824
EOF

# Create traffic matrix for cross-ToR flow  
cat > /tmp/cross_tor_builtin.tm << EOF
Nodes 8
Connections 1
Triggers 0
Failures 0

0->5 start 0 size 1073741824
EOF

cd sim/datacenter

echo "=== Running Same-ToR Flow Test (0→1) ==="
echo "Expected: Faster completion (2-hop path)"

./htsim_ndp \
    -nodes 8 \
    -tiers 2 \
    -tm /tmp/same_tor_builtin.tm \
    -linkspeed 1000 \
    -strat ecmp_host \
    -paths 1 \
    -end 20000000 \
    -o /tmp/same_tor_builtin_results.log > /tmp/same_tor_builtin_output.txt 2>&1

if [ $? -eq 0 ]; then
    echo "✓ Same-ToR test completed successfully"
    echo ""
    echo "Same-ToR Results:"
    ../../sim/parse_output /tmp/same_tor_builtin_results.log -ndp -completion
    SAME_TOR_SUCCESS=1
else
    echo "✗ Same-ToR test failed"
    echo "HTSIM output:"
    cat /tmp/same_tor_builtin_output.txt
    SAME_TOR_SUCCESS=0
fi

echo ""
echo "=== Running Cross-ToR Flow Test (0→5) ==="
echo "Expected: Slower completion (4-hop path through aggregation)"

./htsim_ndp \
    -nodes 8 \
    -tiers 2 \
    -tm /tmp/cross_tor_builtin.tm \
    -linkspeed 1000 \
    -strat ecmp_host \
    -paths 1 \
    -end 20000000 \
    -o /tmp/cross_tor_builtin_results.log > /tmp/cross_tor_builtin_output.txt 2>&1

if [ $? -eq 0 ]; then
    echo "✓ Cross-ToR test completed successfully"
    echo ""
    echo "Cross-ToR Results:"
    ../../sim/parse_output /tmp/cross_tor_builtin_results.log -ndp -completion
    CROSS_TOR_SUCCESS=1
else
    echo "✗ Cross-ToR test failed"
    echo "HTSIM output:"
    cat /tmp/cross_tor_builtin_output.txt
    CROSS_TOR_SUCCESS=0
fi

cd ../..

echo ""
echo "=== Detailed Analysis ==="

if [ "$SAME_TOR_SUCCESS" -eq 1 ]; then
    echo "Same-ToR flow (Host 0 → Host 1):"
    ./sim/parse_output /tmp/same_tor_builtin_results.log -ndp -show | head -3
fi

echo ""

if [ "$CROSS_TOR_SUCCESS" -eq 1 ]; then
    echo "Cross-ToR flow (Host 0 → Host 5):"
    ./sim/parse_output /tmp/cross_tor_builtin_results.log -ndp -show | head -3
fi

echo ""
echo "=== Topology Verification ==="
echo "Let's verify which ToR each host connects to in HTSIM's built-in 8-node topology:"
./experiments/simple_examples/verify_htsim_routing.sh 0 1 built-in | head -10
echo ""
./experiments/simple_examples/verify_htsim_routing.sh 0 5 built-in | head -10

echo ""
echo "=== Performance Analysis ==="
echo "In a 2-tier, 8-node fat-tree (K=4):"
echo "  • Host 0,1,2,3 → ToR-0"
echo "  • Host 4,5,6,7 → ToR-1"
echo "  • Flow 0→1: Same ToR (2 hops)"
echo "  • Flow 0→5: Cross ToR (4 hops via aggregation)"
echo ""
echo "Expected performance difference with 1GB flows:"
echo "  • Same-ToR should complete significantly faster"
echo "  • Cross-ToR has more latency and uplink bandwidth sharing"
echo "  • Difference should be much more noticeable than with 100MB flows"

echo ""
echo "=== Files Created ==="
echo "  Same-ToR results: /tmp/same_tor_builtin_results.log"
echo "  Cross-ToR results: /tmp/cross_tor_builtin_results.log"
echo "  Traffic matrices: /tmp/same_tor_builtin.tm, /tmp/cross_tor_builtin.tm"