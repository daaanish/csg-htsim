#!/usr/bin/env bash
# K Calculation Demonstrator
# Shows exactly how HTSIM calculates K from node count

echo "=== How HTSIM Calculates K from Node Count ==="
echo ""

NODES=${1:-8}
TIERS=${2:-2}

echo "Input: -nodes $NODES -tiers $TIERS"
echo ""

if [ "$TIERS" = "2" ]; then
    echo "2-Tier Leaf-Spine Calculation:"
    echo "==============================="
    echo ""
    echo "HTSIM's actual algorithm from fat_tree_topology.cpp:"
    echo "  K = 0"
    echo "  while (_no_of_nodes < no_of_nodes) {"
    echo "      K++"
    echo "      _no_of_nodes = K * K / 2"
    echo "  }"
    echo "  BUT: Requires EXACT capacity match (no overprovisioning)"
    echo "  Result: Only even K values work for integer node counts"
    echo ""
    echo "Effective behavior: K increments by 2 (even values only):"
    echo ""
    
    # Show only even K values (what actually works in HTSIM)
    for K in 2 4 6 8; do
        CAPACITY=$((K * K / 2))
        echo "Try K=$K: K²/2 = $K²/2 = $CAPACITY hosts"
        
        if [ $CAPACITY -ge $NODES ]; then
            echo "  ✓ $CAPACITY >= $NODES, so K=$K works!"
            echo ""
            echo "With K=$K, the topology structure is:"
            echo "  • Each ToR switch: K/2 = $K/2 = $((K/2)) host ports"
            echo "  • Each ToR switch: K/2 = $K/2 = $((K/2)) uplink ports"
            echo "  • Number of ToR switches: K = $K"
            echo "  • Number of Agg switches: K/2 = $K/2 = $((K/2))"
            echo "  • Total host capacity: $K ToRs × $((K/2)) hosts = $CAPACITY"
            echo ""
            echo "Why this gives $NODES hosts:"
            echo "  • ToR-0: hosts $((K/2 * 0))-$((K/2 * 1 - 1))"
            echo "  • ToR-1: hosts $((K/2 * 1))-$((K/2 * 2 - 1))"
            echo "  • ToR-2: hosts $((K/2 * 2))-$((K/2 * 3 - 1))"
            echo "  • ToR-3: hosts $((K/2 * 3))-$((K/2 * 4 - 1))"
            echo "  = Total: $CAPACITY hosts (uses first $NODES)"
            break
        else
            echo "  ✗ $CAPACITY < $NODES, too small"
        fi
    done
    
elif [ "$TIERS" = "3" ]; then
    echo "3-Tier Fat-Tree Calculation:"
    echo "============================="
    echo ""
    echo "HTSIM's actual algorithm from fat_tree_topology.cpp:"
    echo "  K = 0"
    echo "  while (_no_of_nodes < no_of_nodes) {"
    echo "      K++"
    echo "      _no_of_nodes = K * K * K / 4"
    echo "  }"
    echo ""
    echo "Incrementing K by 1 until capacity >= nodes:"
    echo ""
    
    # Try different K values starting from 1 (like HTSIM)
    for K in 1 2 3 4 5 6 7 8; do
        CAPACITY=$((K * K * K / 4))
        echo "Try K=$K: K³/4 = $K³/4 = $CAPACITY hosts"
        
        if [ $CAPACITY -ge $NODES ]; then
            echo "  ✓ $CAPACITY >= $NODES, so K=$K works!"
            echo ""
            echo "With K=$K, the 3-tier fat-tree has:"
            echo "  • $K pods with $((K/2)) hosts each"
            echo "  • $((K/2)) ToR switches per pod"
            echo "  • $((K/2)) Agg switches per pod"
            echo "  • $((K*K/4)) Core switches"
            echo "  • Total hosts: K³/4 = $CAPACITY"
            break
        else
            echo "  ✗ $CAPACITY < $NODES, too small"
        fi
    done
    echo "============================"
    echo ""
    echo "Formula: K³/4 >= nodes"
    echo "Need to find smallest K where K³/4 >= $NODES"
    echo ""
    
    # Try different K values
    for K in 2 3 4 5 6; do
        CAPACITY=$((K * K * K / 4))
        echo "Try K=$K: K³/4 = $K³/4 = $CAPACITY hosts"
        
        if [ $CAPACITY -ge $NODES ]; then
            echo "  ✓ $CAPACITY >= $NODES, so K=$K works!"
            echo ""
            echo "With K=$K, the 3-tier structure is:"
            echo "  • Each switch: K/2 down + K/2 up = $((K/2)) + $((K/2))"
            echo "  • ToR switches: K²/2 = $((K*K/2))"
            echo "  • Agg switches: K²/2 = $((K*K/2))"  
            echo "  • Core switches: K²/4 = $((K*K/4))"
            echo "  • Total capacity: $CAPACITY hosts"
            break
        else
            echo "  ✗ $CAPACITY < $NODES, too small"
        fi
    done
fi

echo ""
echo "=== Summary ==="
echo "Input: $NODES nodes → Output: K found"
echo "HTSIM's algorithm: Start K=0, increment K++ until capacity >= node count"
echo "Source: sim/datacenter/fat_tree_topology.cpp, set_params() function"