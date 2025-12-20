#!/usr/bin/env bash
# HTSIM Topology Visualizer
# Shows the actual topology structure being used

if [ $# -lt 1 ]; then
    echo "Usage: $0 <htsim_command...>"
    echo "Example: $0 ./htsim_ndp -nodes 8 -tiers 2"
    echo "This will show the topology structure without running simulation"
    exit 1
fi

cd "$(dirname "$0")/../../sim/datacenter"

# Extract key parameters
NODES=""
TIERS=""
TOPO_FILE=""
LINKSPEED=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -nodes)
            NODES="$2"
            shift 2
            ;;
        -tiers)
            TIERS="$2" 
            shift 2
            ;;
        -topo)
            TOPO_FILE="$2"
            shift 2
            ;;
        -linkspeed)
            LINKSPEED="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo "=== HTSIM Topology Visualization ==="
echo "Nodes: ${NODES:-auto}"
echo "Tiers: ${TIERS:-3}"
echo "Topology file: ${TOPO_FILE:-built-in}"
echo "Link speed: ${LINKSPEED:-default} Mbps"
echo ""

if [ -n "$TOPO_FILE" ]; then
    echo "=== Custom Topology File Analysis ==="
    if [ -f "$TOPO_FILE" ]; then
        echo "File: $TOPO_FILE"
        echo ""
        
        # Parse key parameters
        NODES_FILE=$(grep "^nodes" "$TOPO_FILE" | awk '{print $2}')
        TIERS_FILE=$(grep "^tiers" "$TOPO_FILE" | awk '{print $2}')
        PODSIZE=$(grep "^podsize" "$TOPO_FILE" | awk '{print $2}')
        
        echo "Parsed from file:"
        echo "  Nodes: $NODES_FILE"
        echo "  Tiers: $TIERS_FILE" 
        echo "  Pod size: $PODSIZE"
        echo ""
        
        # Show tier details
        tier=0
        while grep -q "^tier $tier" "$TOPO_FILE"; do
            echo "--- Tier $tier ---"
            awk "/^tier $tier/,/^tier [0-9]|^\$/" "$TOPO_FILE" | grep -v "^tier [0-9]" | sed 's/^/  /'
            echo ""
            tier=$((tier + 1))
        done
    else
        echo "ERROR: Topology file not found: $TOPO_FILE"
        exit 1
    fi
else
    echo "=== Built-in Topology Analysis ==="
    
    # Default calculations for built-in topologies
    NODES=${NODES:-8}
    TIERS=${TIERS:-2}
    
    if [ "$TIERS" = "2" ]; then
        # HTSIM's algorithm: K starts at 0, increments until K*K/2 >= NODES  
        K=0
        while [ $((K * K / 2)) -lt $NODES ]; do
            K=$((K + 1))
        done
        
        ACTUAL_NODES=$((K * K / 2))
        HOSTS_PER_POD=$ACTUAL_NODES
        TOR_SWITCHES=$K
        AGG_SWITCHES=$((K / 2))
        CORE_SWITCHES=0
        PODS=1
        
        echo "2-Tier Leaf-Spine Topology (K=$K):"
        echo "  Actual nodes: $ACTUAL_NODES"
        echo "  Pods: $PODS"
        echo "  Hosts per pod: $HOSTS_PER_POD"
        echo "  ToR switches: $TOR_SWITCHES"
        echo "  Aggregation switches: $AGG_SWITCHES"
        echo "  Core switches: $CORE_SWITCHES"
        echo ""
        echo "Switch radix:"
        echo "  ToR down-ports: $((K/2)) (to hosts)"
        echo "  ToR up-ports: $((K/2)) (to aggregation)"
        echo "  Agg down-ports: $((K/2)) (to ToRs)"
        
    elif [ "$TIERS" = "3" ]; then
        # HTSIM's algorithm: K starts at 0, increments until K^3/4 >= NODES
        K=0
        while [ $((K * K * K / 4)) -lt $NODES ]; do
            K=$((K + 1))
        done
        
        ACTUAL_NODES=$((K * K * K / 4))
        HOSTS_PER_POD=$((K * K / 4))
        TOR_SWITCHES=$((K * K / 2))
        AGG_SWITCHES=$((K * K / 2))
        CORE_SWITCHES=$((K * K / 4))
        PODS=$K
        
        echo "3-Tier Fat-Tree Topology (K=$K):"
        echo "  Actual nodes: $ACTUAL_NODES"
        echo "  Pods: $PODS"
        echo "  Hosts per pod: $HOSTS_PER_POD"
        echo "  ToR switches: $TOR_SWITCHES"
        echo "  Aggregation switches: $AGG_SWITCHES"
        echo "  Core switches: $CORE_SWITCHES"
        echo ""
        echo "Switch radix:"
        echo "  ToR down-ports: $((K/2)) (to hosts)"
        echo "  ToR up-ports: $((K/2)) (to aggregation)"
        echo "  Agg down-ports: $((K/2)) (to ToRs)"
        echo "  Agg up-ports: $((K/2)) (to core)"
        echo "  Core down-ports: $K (to aggregation)"
    fi
fi

echo ""
echo "=== Topology Diagram ==="

# Generate ASCII diagram
if [ -n "$TOPO_FILE" ] && [ -f "$TOPO_FILE" ]; then
    # For custom topology files
    NODES_FILE=$(grep "^nodes" "$TOPO_FILE" | awk '{print $2}')
    TIERS_FILE=$(grep "^tiers" "$TOPO_FILE" | awk '{print $2}')
    
    if [ "$NODES_FILE" = "2" ] && [ "$TIERS_FILE" = "2" ]; then
        echo "2-Host, 2-Tier Topology:"
        echo ""
        echo "    [Agg-0]"
        echo "       |"
        echo "    [ToR-0]"
        echo "     /   \\"
        echo " Host-0  Host-1"
        echo ""
    elif [ "$NODES_FILE" = "4" ] && [ "$TIERS_FILE" = "2" ]; then
        echo "4-Host, 2-Tier Topology:"
        echo ""
        echo "      [Agg-0]"
        echo "      /     \\"
        echo "  [ToR-0]  [ToR-1]"
        echo "   /   \\    /   \\"
        echo "  H-0  H-1 H-2  H-3"
        echo ""
    fi
else
    # For built-in topologies
    if [ "$TIERS" = "2" ] && [ "$NODES" = "8" ]; then
        echo "8-Host, 2-Tier Leaf-Spine (K=4):"
        echo ""
        echo "    [Agg-0]   [Agg-1]"
        echo "    /  |  \\   /  |  \\"
        echo "[ToR-0][ToR-1][ToR-2][ToR-3]"
        echo " /|\\    /|\\    /|\\    /|\\"
        echo "H0H1   H2H3   H4H5   H6H7"
        echo ""
    elif [ "$TIERS" = "3" ] && [ "$NODES" = "8" ]; then
        echo "8-Host, 3-Tier Fat-Tree (K=4):"
        echo ""
        echo "       [Core-0] [Core-1]"
        echo "        /    \\   /    \\"
        echo "    [Agg-0] [Agg-1] [Agg-2] [Agg-3]"
        echo "     |   \\   /   |   |   \\   /   |"
        echo "  [ToR-0][ToR-1] [ToR-2][ToR-3]"
        echo "   /|\\   /|\\     /|\\   /|\\"
        echo "  H0H1  H2H3    H4H5  H6H7"
        echo ""
        echo "Pod-0: H0,H1,H2,H3  Pod-1: H4,H5,H6,H7"
    fi
fi

echo "=== Host-to-Host Path Examples ==="
echo ""

if [ -n "$TOPO_FILE" ] && [ -f "$TOPO_FILE" ]; then
    NODES_FILE=$(grep "^nodes" "$TOPO_FILE" | awk '{print $2}')
    if [ "$NODES_FILE" = "2" ]; then
        echo "Host 0 → Host 1: Host-0 → ToR-0 → Host-1 (same ToR)"
    elif [ "$NODES_FILE" = "4" ]; then
        echo "Host 0 → Host 1: Host-0 → ToR-0 → Host-1 (same ToR)"
        echo "Host 0 → Host 2: Host-0 → ToR-0 → Agg-0 → ToR-1 → Host-2 (cross-ToR)"
    fi
else
    if [ "$NODES" = "8" ] && [ "$TIERS" = "2" ]; then
        echo "Host 0 → Host 1: Host-0 → ToR-0 → Host-1 (same ToR)"
        echo "Host 0 → Host 2: Host-0 → ToR-0 → Agg-0 → ToR-1 → Host-2 (cross-ToR)"
        echo "Host 0 → Host 4: Host-0 → ToR-0 → Agg-1 → ToR-2 → Host-4 (cross-ToR)"
    elif [ "$NODES" = "8" ] && [ "$TIERS" = "3" ]; then
        echo "Host 0 → Host 1: Host-0 → ToR-0 → Host-1 (same ToR, same pod)"
        echo "Host 0 → Host 2: Host-0 → ToR-0 → Agg-0 → ToR-1 → Host-2 (same pod)"
        echo "Host 0 → Host 4: Host-0 → ToR-0 → Agg-0 → Core-0 → Agg-2 → ToR-2 → Host-4 (cross-pod)"
    fi
fi

echo ""
echo "=== Traffic Matrix Recommendations ==="
echo ""
echo "For interesting experiments with this topology:"

if [ -n "$TOPO_FILE" ] && [ -f "$TOPO_FILE" ]; then
    NODES_FILE=$(grep "^nodes" "$TOPO_FILE" | awk '{print $2}')
    case $NODES_FILE in
        2)
            echo "• 0→1: Single flow (same ToR)"
            ;;
        4)
            echo "• 0→1: Same ToR flow"
            echo "• 0→2: Cross-ToR flow"
            echo "• 0→2, 1→3: Competing cross-ToR flows"
            ;;
    esac
else
    case $NODES in
        8)
            echo "• 0→1: Same ToR flow"
            echo "• 0→4: Cross-ToR flow"
            echo "• 0→4, 1→5: Parallel cross-ToR flows"
            echo "• 0→7, 1→7, 2→7: Incast to Host 7"
            if [ "$TIERS" = "3" ]; then
                echo "• 0→4: Cross-pod flow (uses core switches)"
            fi
            ;;
    esac
fi

echo ""