# HTSIM Topology Visualization Guide

## Problem Solved
HTSIM topology setups can be confusing because:
- The relationship between nodes, switches, and tiers isn't obvious
- You can't easily see what path packets take through the network
- Built-in topologies use complex calculations (K-ary fat-trees)
- Custom topology files have many parameters to understand

## Solution: Visualization Tools

### 1. Complete Analysis: `analyze_topology.sh`
**Best starting point** - Shows everything about a topology:

```bash
# Analyze any HTSIM configuration:
./experiments/simple_examples/analyze_topology.sh -nodes 8 -tiers 2
./experiments/simple_examples/analyze_topology.sh -nodes 4 -topo topos/simple_4host.topo
```

**What it shows:**
- ASCII diagram of the network structure
- Switch counts and port allocations  
- Example flow paths (same-ToR vs cross-ToR)
- Performance implications and bottlenecks
- Ready-to-use traffic matrix examples
- Suggested experiments

### 2. Topology Structure: `visualize_topology.sh`
Shows the network layout and calculates switch counts:

```bash
./experiments/simple_examples/visualize_topology.sh ./htsim_ndp -nodes 8 -tiers 2
```

**Example output for 8-node, 2-tier:**
```
    [Agg-0]   [Agg-1]        ← 2 aggregation switches (NOT counted in nodes)
    /  |  \   /  |  \
[ToR-0][ToR-1][ToR-2][ToR-3]  ← 4 ToR switches (NOT counted in nodes)
 /|\    /|\    /|\    /|\
H0H1   H2H3   H4H5   H6H7     ← 8 hosts = 8 nodes (THESE are the "nodes")
```

**Important**: Only hosts (H0-H7) count toward the 8 nodes. Switches are network infrastructure.

### 3. Flow Path Tracing: `trace_flow_path.sh`
Shows exactly which switches a specific flow traverses:

```bash
./experiments/simple_examples/trace_flow_path.sh 0 4 -nodes 8 -tiers 2
```

**Example output:**
```
=== CROSS-TOR, CROSS-AGG PATH ===
Host-0 → ToR-0 → Agg-0 → Agg-1 → ToR-2 → Host-4

Hops: 7 (Host → ToR → Agg → Agg → ToR → Host)
Queues: Host-0 → ToR-0 uplink → Agg-0 → Agg-1 → ToR-2 downlink → Host-4
Bottleneck: Inter-aggregation links
```

## Key Insights Revealed

### Node vs Switch Terminology
- **Nodes/Hosts**: Traffic endpoints that generate/receive data (H0, H1, H2...)
  - These are what you specify with `-nodes N`
  - They appear in traffic matrices as sources and destinations
- **ToR switches**: Connect hosts to network (ToR-0, ToR-1...)  
  - NOT counted in the node total
  - Created automatically based on topology requirements
- **Aggregation switches**: Connect ToRs together (Agg-0, Agg-1...)
  - NOT counted in the node total
  - Number depends on topology size and tier structure
- **Core switches**: Connect pods in 3-tier topologies
  - NOT counted in the node total
  - Only exist in 3-tier fat-tree topologies

### Path Types and Performance
1. **Same-ToR paths** (e.g., 0→1): 
   - Shortest (3 hops)
   - Highest bandwidth
   - No uplink contention

2. **Cross-ToR paths** (e.g., 0→4):
   - Longer (5-7 hops)
   - Potential bottlenecks at uplinks
   - Shared with other cross-ToR traffic

### Built-in Topology Calculations
When you specify `-nodes N`, HTSIM calculates how many switches are needed:

**What is K?**
K is the **switch radix** (number of ports per switch) in fat-tree topologies. It determines:
- How many hosts connect to each ToR switch
- How many uplinks each switch has
- The overall structure and scale of the network

**2-tier leaf-spine**: Creates K×K/2 hosts, where K is calculated to fit your node count
- Each ToR has K/2 downlinks (to hosts) and K/2 uplinks (to aggregation)
- Example: `-nodes 8` → K=4 → each ToR has 2 host ports + 2 uplinks
- Result: 8 hosts + 4 ToRs + 2 aggregation switches

**3-tier fat-tree**: Creates K³/4 hosts, where K creates a full fat-tree
- Each switch has K/2 down-ports and K/2 up-ports
- Example: `-nodes 8` → K=4 → 8 hosts + 8 ToRs + 8 agg + 4 core switches

**K calculation examples:**
- For 8 nodes, 2-tier: Need K where K²/2 ≥ 8 → K=4 works (4²/2 = 8)
- For 8 nodes, 3-tier: Need K where K³/4 ≥ 8 → K=4 works (4³/4 = 16, rounded down to 8)
- For 6 nodes, 2-tier: Need K where K²/2 ≥ 6 → K=4 works (gives 8 hosts, rounds up)

HTSIM rounds up to the next valid K if needed.
**The switch count is calculated automatically - you only specify host count.**

## Quick Usage Examples

### See topology structure:
```bash
./experiments/simple_examples/analyze_topology.sh -nodes 8 -tiers 2
```

### Compare flow types:
```bash
# Same-ToR (fast):
./experiments/simple_examples/trace_flow_path.sh 0 1 -nodes 8 -tiers 2

# Cross-ToR (slower):
./experiments/simple_examples/trace_flow_path.sh 0 4 -nodes 8 -tiers 2
```

### Test custom topology:
```bash
./experiments/simple_examples/analyze_topology.sh -nodes 4 -topo ../../experiments/simple_examples/topos/simple_4host.topo
```

## Understanding Your Results

### Traffic Matrix Design
The tools suggest realistic traffic patterns:
- **Bandwidth comparison**: Same-ToR vs cross-ToR flows
- **Congestion testing**: Multiple flows sharing uplinks  
- **Incast scenarios**: Many senders to one receiver

### Performance Expectations
- **Same-ToR flows**: Should complete fastest
- **Cross-ToR flows**: Slower due to more hops and shared uplinks
- **Competing flows**: Throughput drops when sharing bottleneck links

### Bottleneck Identification
The tools identify likely congestion points:
- ToR uplinks (most common)
- Aggregation switch capacity
- Core switches (in 3-tier topologies)
- Host network interfaces

## Integration with HTSIM

Use the visualization tools **before** running simulations to:
1. Understand what topology will actually be built
2. Design traffic matrices that test specific paths
3. Predict where congestion will occur
4. Choose appropriate flow sizes and timing

Use the suggested traffic matrices as starting points for your experiments.