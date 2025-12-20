# Understanding K in HTSIM Fat-Tree Topologies

## What is K?

**K** is the **switch radix** - the total number of ports on each switch in a fat-tree topology.

## How HTSIM Calculates K from Node Count

HTSIM uses this algorithm from `sim/datacenter/fat_tree_topology.cpp`:

### 2-Tier (Leaf-Spine):
```cpp
K = 0;
while (_no_of_nodes < no_of_nodes) {
    K++;
    _no_of_nodes = K * K / 2;
}
```

### 3-Tier (Full Fat-Tree):
```cpp
K = 0;
while (_no_of_nodes < no_of_nodes) {
    K++;
    _no_of_nodes = K * K * K / 4;
}
```

**Key Point**: HTSIM increments K starting from 0 until the capacity formula accommodates your node count.

## Key Principle: K/2 Rule

In fat-tree topologies, each switch uses its K ports as:
- **K/2 ports downward** (to lower tier or hosts)
- **K/2 ports upward** (to higher tier)

## Concrete Example: K=4

When HTSIM calculates K=4 for your topology:

```
Each ToR switch has 4 ports total:
├── 2 down-ports → connect to 2 hosts each
└── 2 up-ports → connect to aggregation switches

Each Aggregation switch has 4 ports total:
├── 2 down-ports → connect to 2 ToR switches  
└── 2 up-ports → (unused in 2-tier, would go to core in 3-tier)
```

## Visual Example: 8 nodes, K=4

```
         [Agg-0]    [Agg-1]
         2 ports    2 ports down
         down ↓      ↓
    ┌─────────┼──────┼─────────┐
    ↓         ↓      ↓         ↓
[ToR-0]   [ToR-1] [ToR-2]   [ToR-3]
2 hosts   2 hosts 2 hosts   2 hosts
   ↓         ↓       ↓         ↓
 H0 H1     H2 H3   H4 H5     H6 H7
```

Each ToR: K=4 ports = 2 down (hosts) + 2 up (agg)
Each Agg: K=4 ports = 2 down (ToRs) + 2 unused

## Why K Matters

**K determines scale:**
- Bigger K = more hosts per ToR
- Bigger K = more switches needed
- Bigger K = higher port density requirements

**Common K values:**
- K=4: Small networks (8-16 hosts)
- K=8: Medium networks (32-128 hosts)  
- K=16: Large networks (512-4096 hosts)

## HTSIM's K Calculation

When you request `-nodes N`, HTSIM finds the smallest K that can accommodate N hosts:

**2-tier (leaf-spine):**
- Formula: K²/2 ≥ N
- Example: N=8 → try K=4 → 4²/2 = 8 ✓

**3-tier (fat-tree):**
- Formula: K³/4 ≥ N  
- Example: N=8 → try K=4 → 4³/4 = 16 ≥ 8 ✓

**If no exact match:** HTSIM rounds up to next valid K
- Example: N=6 → K=4 → gives 8 hosts (rounds up)

## Practical Implications

**Higher K means:**
- ✅ More hosts per network
- ✅ Better bisection bandwidth
- ❌ More expensive switches (more ports)
- ❌ More complex cabling

**Lower K means:**
- ✅ Cheaper switches (fewer ports)
- ✅ Simpler to build
- ❌ Fewer hosts supported
- ❌ Lower aggregate bandwidth

## In Your Simulations

You don't directly control K - you specify `-nodes N` and HTSIM picks the appropriate K. But understanding K helps you predict:

- How many switches will be created
- What the bandwidth characteristics will be
- Why certain node counts get "rounded up"

The visualization tools show you the calculated K value so you can understand the resulting topology structure.