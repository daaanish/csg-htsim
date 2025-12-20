#!/bin/bash
# Simple TCP Experiment Script
# Demonstrates basic usage of htsim_tcp

echo "=== HTSIM TCP Simple Experiment ==="
echo ""

# 1. Single-path TCP with uncoupled congestion control
echo "1. Running single-path TCP (16 nodes, 8 connections)..."
./htsim_tcp -nodes 16 -conns 8 -sub 1 -o example1.log UNCOUPLED 2>&1 | head -20 &
PID=$!
sleep 5
kill $PID 2>/dev/null
wait $PID 2>/dev/null
echo "   ✓ Simulation completed (truncated)"

# 2. Parse the results
if [ -f example1.log ]; then
    echo ""
    echo "2. Parsing throughput results..."
    ../parse_output example1.log -show 2>&1 | head -20
fi

echo ""
echo "=== Multipath TCP Example ==="

# 3. MPTCP with 2 subflows
echo "3. Running MPTCP with 2 subflows (coupled epsilon)..."
./htsim_tcp -nodes 16 -conns 8 -sub 2 -o example2.log COUPLED_EPSILON 0.5 2>&1 | head -20 &
PID=$!
sleep 5
kill $PID 2>/dev/null
wait $PID 2>/dev/null
echo "   ✓ Simulation completed (truncated)"

if [ -f example2.log ]; then
    echo ""
    echo "4. Parsing MPTCP results..."
    ../parse_output example2.log -show 2>&1 | head -20
fi

echo ""
echo "=== Files Created ==="
ls -lh example*.log 2>/dev/null | awk '{print $9, $5}'

echo ""
echo "=== Next Steps ==="
echo "• View full ASCII log: ../parse_output example1.log -ascii > example1_ascii.txt"
echo "• Queue statistics: ../parse_output example1.log -queue"
echo "• Filter specific flow: ../parse_output example1.log -filter 0 5 -show"
echo "• Compare algorithms: Try FULLY_COUPLED, COUPLED_TCP, etc."
echo ""
echo "See TCP_QUICKSTART.md for full documentation!"
