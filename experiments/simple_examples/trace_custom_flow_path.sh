#!/usr/bin/env bash
# Trace flow paths through custom HTSIM topologies

if [ $# -lt 3 ]; then
    echo "Usage: $0 <src_host> <dst_host> <topology_file.topo>"
    echo "Example: $0 0 3 topos/test-ipad.topo"
    echo ""
    echo "This traces the path from source to destination host through your custom topology"
    exit 1
fi

SRC="$1"
DST="$2"
TOPO_FILE="$3"

if [ ! -f "$TOPO_FILE" ]; then
    echo "Error: Topology file '$TOPO_FILE' not found"
    exit 1
fi

echo "=== Flow Path Analysis: Host $SRC → Host $DST ==="
echo "Topology: $(basename $TOPO_FILE)"
echo ""

# Parse topology file
NODES=$(grep "^nodes" "$TOPO_FILE" | awk '{print $2}')
TIERS=$(grep "^tiers" "$TOPO_FILE" | awk '{print $2}')

if [ "$SRC" -ge "$NODES" ] || [ "$DST" -ge "$NODES" ]; then
    echo "Error: Host ID must be between 0 and $((NODES-1))"
    exit 1
fi

if [ "$SRC" -eq "$DST" ]; then
    echo "Error: Source and destination must be different"
    exit 1
fi

# Get ToR parameters
TOR_DOWNPORTS=$(grep -A 10 "^tier 0" "$TOPO_FILE" | grep "radix_down" | awk '{print $2}')
TOR_UPPORTS=$(grep -A 10 "^tier 0" "$TOPO_FILE" | grep "radix_up" | awk '{print $2}')

# Calculate which ToR each host connects to
SRC_TOR=$((SRC / TOR_DOWNPORTS))
DST_TOR=$((DST / TOR_DOWNPORTS))

echo "Host Placement:"
echo "  Host $SRC → ToR-$SRC_TOR (port $((SRC % TOR_DOWNPORTS)))"
echo "  Host $DST → ToR-$DST_TOR (port $((DST % TOR_DOWNPORTS)))"
echo ""

if [ "$SRC_TOR" = "$DST_TOR" ]; then
    echo "=== SAME-TOR FLOW ==="
    echo "Path: Host$SRC → ToR-$SRC_TOR → Host$DST"
    echo ""
    echo "Flow characteristics:"
    echo "  • Hops: 2 (host→ToR→host)"
    echo "  • Latency: 2 × link_latency + 1 × switch_latency"
    echo "  • Bandwidth: Limited by ToR downlink speed"
    echo "  • Congestion: Only at ToR-$SRC_TOR"
    echo ""
    echo "This is the FASTEST possible path - stays within one ToR switch."
else
    echo "=== CROSS-TOR FLOW ==="
    if [ "$TIERS" = "2" ]; then
        # 2-tier: goes through aggregation
        AGG_DOWNPORTS=$(grep -A 10 "^tier 1" "$TOPO_FILE" | grep "radix_down" | awk '{print $2}')
        
        # Simple mapping - in practice this depends on the routing algorithm
        SRC_AGG=$((SRC_TOR / AGG_DOWNPORTS))
        DST_AGG=$((DST_TOR / AGG_DOWNPORTS))
        
        echo "Path: Host$SRC → ToR-$SRC_TOR → Agg-$SRC_AGG → ToR-$DST_TOR → Host$DST"
        echo ""
        echo "Flow characteristics:"
        echo "  • Hops: 4 (host→ToR→Agg→ToR→host)"
        echo "  • Latency: 4 × link_latency + 3 × switch_latency"
        echo "  • Bandwidth: Limited by weakest link (usually uplinks)"
        echo "  • Congestion: At ToR-$SRC_TOR uplinks, Agg-$SRC_AGG, ToR-$DST_TOR downlinks"
        echo ""
        echo "This is a SPINE flow - goes through aggregation layer."
    else
        echo "3-tier path analysis not implemented for custom topologies yet."
    fi
fi

echo ""
echo "=== Performance Implications ==="

# Get speed information
DOWNLINK_SPEED=$(grep -A 10 "^tier 0" "$TOPO_FILE" | grep "downlink_speed_gbps" | awk '{print $2}')
UPLINK_SPEED=$(grep -A 10 "^tier 1" "$TOPO_FILE" | grep "downlink_speed_gbps" | awk '{print $2}')

echo "Link Speeds:"
echo "  • Host↔ToR: ${DOWNLINK_SPEED}Gbps"
echo "  • ToR↔Agg: ${UPLINK_SPEED}Gbps"
echo ""

if [ "$SRC_TOR" != "$DST_TOR" ]; then
    echo "Bottleneck Analysis:"
    echo "  • If uplink speed < downlink speed: Uplinks are bottleneck"
    echo "  • Multiple flows sharing uplinks → More congestion"
    echo "  • ToR-$SRC_TOR has $TOR_UPPORTS uplinks to share among $TOR_DOWNPORTS hosts"
    echo "  • Oversubscription ratio determines congestion likelihood"
fi

echo ""
echo "=== Traffic Matrix Specification ==="
echo "To test this specific flow in HTSIM traffic matrix:"
echo ""
echo "Nodes 2"
echo "Connections 1" 
echo "Triggers 0"
echo "Failures 0"
echo "$SRC $DST 0 100000000000"
echo ""
echo "This sends traffic from host $SRC to host $DST starting at time 0."