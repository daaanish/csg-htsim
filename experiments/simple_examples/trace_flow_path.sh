#!/usr/bin/env bash
# HTSIM Flow Path Tracer
# Shows the exact path packets take for specific flows

if [ $# -lt 3 ]; then
    echo "Usage: $0 <src> <dst> <topology_params...>"
    echo "Example: $0 0 4 -nodes 8 -tiers 2"
    echo "Example: $0 0 1 -nodes 4 -topo ../../experiments/simple_examples/topos/simple_4host.topo"
    exit 1
fi

SRC=$1
DST=$2
shift 2

cd "$(dirname "$0")/../../sim/datacenter"

# Extract topology parameters
NODES=""
TIERS=""
TOPO_FILE=""

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
        *)
            shift
            ;;
    esac
done

echo "=== Flow Path Analysis ==="
echo "Source: Host $SRC"
echo "Destination: Host $DST"
echo ""

if [ -n "$TOPO_FILE" ]; then
    echo "Using topology file: $TOPO_FILE"
    if [ ! -f "$TOPO_FILE" ]; then
        echo "ERROR: Topology file not found"
        exit 1
    fi
    NODES_FILE=$(grep "^nodes" "$TOPO_FILE" | awk '{print $2}')
    TIERS_FILE=$(grep "^tiers" "$TOPO_FILE" | awk '{print $2}')
    NODES=$NODES_FILE
    TIERS=$TIERS_FILE
else
    echo "Using built-in topology"
    NODES=${NODES:-8}
    TIERS=${TIERS:-2}
fi

echo "Topology: $NODES nodes, $TIERS tiers"
echo ""

# Calculate topology structure
if [ "$TIERS" = "2" ]; then
    # Leaf-spine
    K=2
    while [ $((K * K / 2)) -lt $NODES ]; do
        K=$((K + 1))
    done
    
    HOSTS_PER_TOR=$((K / 2))
    
    # Calculate which ToR each host connects to
    SRC_TOR=$((SRC / HOSTS_PER_TOR))
    DST_TOR=$((DST / HOSTS_PER_TOR))
    
    echo "=== Path Calculation ==="
    echo "Hosts per ToR: $HOSTS_PER_TOR"
    echo "Source ToR: $SRC_TOR"
    echo "Destination ToR: $DST_TOR"
    echo ""
    
    if [ $SRC_TOR -eq $DST_TOR ]; then
        echo "=== SAME-TOR PATH ==="
        echo "Host-$SRC → ToR-$SRC_TOR → Host-$DST"
        echo ""
        echo "Hops: 3 (Host → ToR → Host)"
        echo "Switch traversal: 1 ToR switch"
        echo "Bottleneck: ToR switch processing"
    else
        # Find aggregation switch
        # In 2-tier, ToRs connect to agg switches in round-robin fashion
        SRC_AGG=$((SRC_TOR / 2))
        DST_AGG=$((DST_TOR / 2))
        
        if [ $SRC_AGG -eq $DST_AGG ]; then
            echo "=== CROSS-TOR, SAME-AGG PATH ==="
            echo "Host-$SRC → ToR-$SRC_TOR → Agg-$SRC_AGG → ToR-$DST_TOR → Host-$DST"
            echo ""
            echo "Hops: 5 (Host → ToR → Agg → ToR → Host)"
            echo "Switch traversal: 2 ToR switches, 1 Aggregation switch"
            echo "Bottleneck: Aggregation uplink capacity"
        else
            echo "=== CROSS-TOR, CROSS-AGG PATH ==="
            echo "Host-$SRC → ToR-$SRC_TOR → Agg-$SRC_AGG → Agg-$DST_AGG → ToR-$DST_TOR → Host-$DST"
            echo ""
            echo "Hops: 7 (Host → ToR → Agg → Agg → ToR → Host)"
            echo "Switch traversal: 2 ToR switches, 2 Aggregation switches"
            echo "Bottleneck: Inter-aggregation links"
        fi
    fi
    
elif [ "$TIERS" = "3" ]; then
    # Fat-tree
    K=2
    while [ $((K * K * K / 4)) -lt $NODES ]; do
        K=$((K + 1))
    done
    
    HOSTS_PER_POD=$((K * K / 4))
    HOSTS_PER_TOR=$((K / 2))
    
    # Calculate pod and ToR for each host
    SRC_POD=$((SRC / HOSTS_PER_POD))
    DST_POD=$((DST / HOSTS_PER_POD))
    
    SRC_TOR=$(( (SRC % HOSTS_PER_POD) / HOSTS_PER_TOR ))
    DST_TOR=$(( (DST % HOSTS_PER_POD) / HOSTS_PER_TOR ))
    
    echo "=== Path Calculation ==="
    echo "Hosts per pod: $HOSTS_PER_POD"
    echo "Hosts per ToR: $HOSTS_PER_TOR"
    echo "Source pod: $SRC_POD, ToR: $SRC_TOR"
    echo "Destination pod: $DST_POD, ToR: $DST_TOR"
    echo ""
    
    if [ $SRC_POD -eq $DST_POD ]; then
        if [ $SRC_TOR -eq $DST_TOR ]; then
            echo "=== SAME-TOR PATH ==="
            echo "Host-$SRC → ToR-$SRC_TOR → Host-$DST"
            echo ""
            echo "Hops: 3 (Host → ToR → Host)"
            echo "Switch traversal: 1 ToR switch"
        else
            echo "=== SAME-POD, CROSS-TOR PATH ==="
            echo "Host-$SRC → ToR-$SRC_TOR → Agg-X → ToR-$DST_TOR → Host-$DST"
            echo ""
            echo "Hops: 5 (Host → ToR → Agg → ToR → Host)"
            echo "Switch traversal: 2 ToR switches, 1 Aggregation switch"
            echo "Bottleneck: Pod aggregation capacity"
        fi
    else
        echo "=== CROSS-POD PATH ==="
        echo "Host-$SRC → ToR-$SRC_TOR → Agg-X → Core-Y → Agg-Z → ToR-$DST_TOR → Host-$DST"
        echo ""
        echo "Hops: 7 (Host → ToR → Agg → Core → Agg → ToR → Host)"
        echo "Switch traversal: 2 ToR, 2 Aggregation, 1 Core switch"
        echo "Bottleneck: Core switch capacity or inter-pod links"
    fi
fi

echo ""
echo "=== Performance Implications ==="

if [ $SRC_TOR -eq $DST_TOR ]; then
    echo "• Lowest latency (fewest hops)"
    echo "• Highest available bandwidth (no uplink contention)"
    echo "• No interference from other pod traffic"
else
    echo "• Higher latency (more hops and switch processing)"
    echo "• Potential bandwidth bottleneck at uplinks"
    echo "• May compete with other cross-ToR flows"
    if [ "$TIERS" = "3" ] && [ $SRC_POD -ne $DST_POD ]; then
        echo "• Cross-pod traffic uses core switches (most congested)"
    fi
fi

echo ""
echo "=== Queue Analysis ==="
echo "Queues this flow will traverse:"

if [ $SRC_TOR -eq $DST_TOR ]; then
    echo "1. Host-$SRC egress queue"
    echo "2. ToR-$SRC_TOR queue (host → host)"
    echo "3. Host-$DST ingress queue"
else
    echo "1. Host-$SRC egress queue"
    echo "2. ToR-$SRC_TOR uplink queue (to aggregation)"
    echo "3. Aggregation switch queue"
    if [ "$TIERS" = "3" ] && [ $SRC_POD -ne $DST_POD ]; then
        echo "4. Core switch queue"
        echo "5. Destination aggregation switch queue"
    fi
    echo "$(( $(echo "1. Host-$SRC egress queue" | wc -l) + 2 )). ToR-$DST_TOR downlink queue (to host)"
    echo "$(( $(echo "1. Host-$SRC egress queue" | wc -l) + 3 )). Host-$DST ingress queue"
fi

echo ""
echo "=== Suggested Experiments ==="
echo ""

if [ $SRC_TOR -eq $DST_TOR ]; then
    echo "This is a SAME-TOR flow. To see congestion effects, try:"
    echo "• Multiple flows to the same destination ToR"
    echo "• Compare with cross-ToR flows to see difference"
else
    echo "This is a CROSS-TOR flow. To see congestion effects, try:"
    echo "• Multiple flows using the same uplink"
    echo "• Vary flow sizes to see queueing behavior"
    echo "• Compare throughput with same-ToR flows"
fi

# Generate traffic matrix example
echo ""
echo "=== Example Traffic Matrix ==="
echo "To test this path with competing traffic:"
echo ""
echo "Nodes $NODES"
echo "Connections 3" 
echo "Triggers 0"
echo "Failures 0"
echo ""
echo "# Your flow:"
echo "$SRC->$DST start 0 size 104857600"
echo ""

if [ $SRC_TOR -eq $DST_TOR ]; then
    # Add another same-ToR flow
    OTHER_SRC=$((SRC_TOR * HOSTS_PER_TOR))
    if [ $OTHER_SRC -eq $SRC ]; then
        OTHER_SRC=$((OTHER_SRC + 1))
    fi
    OTHER_DST=$((SRC_TOR * HOSTS_PER_TOR + 1))
    if [ $OTHER_DST -eq $DST ] || [ $OTHER_DST -eq $OTHER_SRC ]; then
        OTHER_DST=$((SRC_TOR * HOSTS_PER_TOR))
    fi
    
    echo "# Competing same-ToR flow:"
    echo "$OTHER_SRC->$OTHER_DST start 0 size 52428800"
else
    # Add competing cross-ToR flow using same source ToR
    OTHER_SRC=$((SRC_TOR * HOSTS_PER_TOR))
    if [ $OTHER_SRC -eq $SRC ]; then
        OTHER_SRC=$((OTHER_SRC + 1))
    fi
    OTHER_DST_TOR=$((DST_TOR + 1))
    if [ $OTHER_DST_TOR -ge $((NODES / HOSTS_PER_TOR)) ]; then
        OTHER_DST_TOR=0
    fi
    OTHER_DST=$((OTHER_DST_TOR * HOSTS_PER_TOR))
    
    echo "# Competing cross-ToR flow (same uplink):"
    echo "$OTHER_SRC->$OTHER_DST start 0 size 52428800"
fi

echo ""
echo "# Background flow (different path):"
if [ $NODES -gt 4 ]; then
    BG_SRC=$(( (SRC_TOR + 2) % (NODES / HOSTS_PER_TOR) * HOSTS_PER_TOR ))
    BG_DST=$(( (DST_TOR + 2) % (NODES / HOSTS_PER_TOR) * HOSTS_PER_TOR ))
    echo "$BG_SRC->$BG_DST start 1000 size 26214400"
fi

echo ""