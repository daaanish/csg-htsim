#!/usr/bin/env bash
# Custom Topology Visualizer for HTSIM
# Parses .topo files and shows the actual structure

if [ $# -lt 1 ]; then
    echo "Usage: $0 <topology_file.topo>"
    echo "Example: $0 topos/test-ipad.topo"
    exit 1
fi

TOPO_FILE="$1"

if [ ! -f "$TOPO_FILE" ]; then
    echo "Error: Topology file '$TOPO_FILE' not found"
    exit 1
fi

echo "=== Custom Topology Analysis: $(basename $TOPO_FILE) ==="
echo ""

# Parse the topology file
NODES=$(grep "^nodes" "$TOPO_FILE" | awk '{print $2}')
TIERS=$(grep "^tiers" "$TOPO_FILE" | awk '{print $2}')
PODSIZE=$(grep "^podsize" "$TOPO_FILE" | awk '{print $2}')

echo "Basic Parameters:"
echo "  Nodes: $NODES"
echo "  Tiers: $TIERS" 
echo "  Pod size: $PODSIZE"
echo ""

# Parse tier-specific information
current_tier=""
echo "Tier Configuration:"

while IFS= read -r line; do
    # Skip comments and empty lines
    if [[ "$line" =~ ^#.*$ ]] || [[ -z "$line" ]]; then
        continue
    fi
    
    if [[ "$line" =~ ^tier[[:space:]]+([0-9]+) ]]; then
        current_tier="${BASH_REMATCH[1]}"
        echo "  Tier $current_tier:"
        continue
    fi
    
    if [[ -n "$current_tier" ]]; then
        case "$line" in
            downlink_speed_gbps*)
                speed=$(echo "$line" | awk '{print $2}')
                echo "    Downlink speed: ${speed}Gbps"
                ;;
            radix_up*)
                radix=$(echo "$line" | awk '{print $2}')
                echo "    Uplink ports: $radix"
                ;;
            radix_down*)
                radix=$(echo "$line" | awk '{print $2}')
                echo "    Downlink ports: $radix"
                ;;
            switch_latency_ns*)
                latency=$(echo "$line" | awk '{print $2}')
                echo "    Switch latency: ${latency}ns"
                ;;
            downlink_latency_ns*)
                latency=$(echo "$line" | awk '{print $2}')
                echo "    Link latency: ${latency}ns"
                ;;
            oversubscribed*)
                oversub=$(echo "$line" | awk '{print $2}')
                echo "    Oversubscription: ${oversub}:1"
                ;;
        esac
    fi
done < "$TOPO_FILE"

echo ""

# Generate ASCII visualization for 2-tier custom topology
if [ "$TIERS" = "2" ]; then
    echo "=== ASCII Topology Visualization ==="
    echo ""
    
    # Calculate structure from the parsed parameters
    TOR_DOWNPORTS=$(grep -A 10 "^tier 0" "$TOPO_FILE" | grep "radix_down" | awk '{print $2}')
    TOR_UPPORTS=$(grep -A 10 "^tier 0" "$TOPO_FILE" | grep "radix_up" | awk '{print $2}')
    AGG_DOWNPORTS=$(grep -A 10 "^tier 1" "$TOPO_FILE" | grep "radix_down" | awk '{print $2}')
    
    # Calculate number of switches needed
    if [ -n "$TOR_DOWNPORTS" ] && [ "$TOR_DOWNPORTS" -gt 0 ]; then
        NUM_TORS=$(( (NODES + TOR_DOWNPORTS - 1) / TOR_DOWNPORTS ))  # Ceiling division
        if [ -n "$AGG_DOWNPORTS" ] && [ "$AGG_DOWNPORTS" -gt 0 ]; then
            NUM_AGGS=$(( (NUM_TORS + AGG_DOWNPORTS - 1) / AGG_DOWNPORTS ))  # Ceiling division
        else
            NUM_AGGS=1
        fi
    else
        NUM_TORS=1
        NUM_AGGS=1
    fi
    
    echo "Calculated Structure:"
    echo "  ToR switches: $NUM_TORS (each with $TOR_DOWNPORTS host ports, $TOR_UPPORTS uplinks)"
    echo "  Agg switches: $NUM_AGGS (each with $AGG_DOWNPORTS downlinks)"
    echo "  Total hosts: $NODES"
    echo ""
    
    # Draw the topology
    echo "Topology Diagram:"
    echo ""
    
    # Aggregation tier
    printf "Aggregation:  "
    for ((i=0; i<NUM_AGGS; i++)); do
        printf "[Agg-$i]"
        if [ $i -lt $((NUM_AGGS-1)) ]; then
            printf "    "
        fi
    done
    echo ""
    
    # Connection lines
    printf "              "
    for ((i=0; i<NUM_AGGS; i++)); do
        printf "  |   "
        if [ $i -lt $((NUM_AGGS-1)) ]; then
            printf "     "
        fi
    done
    echo ""
    
    # ToR tier
    printf "ToR:          "
    for ((i=0; i<NUM_TORS; i++)); do
        printf "[ToR-$i]"
        if [ $i -lt $((NUM_TORS-1)) ]; then
            printf "  "
        fi
    done
    echo ""
    
    # Connection lines to hosts
    printf "              "
    for ((i=0; i<NUM_TORS; i++)); do
        printf "  |   "
        if [ $i -lt $((NUM_TORS-1)) ]; then
            printf "   "
        fi
    done
    echo ""
    
    # Hosts
    printf "Hosts:        "
    for ((i=0; i<NODES; i++)); do
        printf "H$i "
        if [ $((i % TOR_DOWNPORTS)) -eq $((TOR_DOWNPORTS-1)) ] && [ $i -lt $((NODES-1)) ]; then
            printf " "
        fi
    done
    echo ""
    echo ""
    
    # Host distribution
    echo "Host Distribution:"
    host_id=0
    for ((tor=0; tor<NUM_TORS; tor++)); do
        printf "  ToR-$tor: hosts "
        for ((port=0; port<TOR_DOWNPORTS && host_id<NODES; port++)); do
            printf "$host_id"
            if [ $port -lt $((TOR_DOWNPORTS-1)) ] && [ $host_id -lt $((NODES-1)) ]; then
                printf ","
            fi
            host_id=$((host_id+1))
        done
        echo ""
    done
fi

echo ""
echo "=== Path Analysis ==="
echo "Use: ./trace_flow_path.sh <src> <dst> $TOPO_FILE"
echo "Example: ./trace_flow_path.sh 0 3 $TOPO_FILE"