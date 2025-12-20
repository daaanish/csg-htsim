# HTSIM Traffic Matrix (.tm) File Complete Guide

## Overview

HTSIM traffic matrix files define network flows, their timing, coordination, and failure scenarios for datacenter network simulations. These files enable modeling complex application patterns, fault tolerance scenarios, and sophisticated flow coordination.

## File Structure

### Basic Format
```
Nodes <number>          # Total hosts in topology
Connections <number>    # Number of flows to create
Triggers <number>       # Number of trigger coordination points
Failures <number>       # Number of link failures to inject

# Flow definitions
<src>-><dst> <parameters>

# Optional trigger definitions  
trigger <parameters>

# Optional failure definitions
failure <parameters>
```

### Header Fields

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `Nodes` | Yes | Total number of hosts in topology | `Nodes 8` |
| `Connections` | Yes | Number of flows to create | `Connections 3` |
| `Triggers` | Yes | Number of trigger coordination points | `Triggers 1` |
| `Failures` | Yes | Number of link failures to inject | `Failures 0` |

## Flow Specifications

### Basic Flow Syntax
```
<src>-><dst> start <time> size <bytes> [optional_parameters]
```

### Flow Parameters

#### Required Parameters
- **`<src>-><dst>`**: Source and destination host IDs (e.g., `0->4`)
- **`size <bytes>`**: Flow size in bytes

#### Start Time Options (Choose One)
- **`start <time>`**: Start at specific time (microseconds)
- **`trigger <id>`**: Wait for trigger ID to fire

#### Optional Parameters
- **`send_done_trigger <id>`**: Fire trigger when transmission completes
- **`recv_done_trigger <id>`**: Fire trigger when reception completes  
- **`prio <priority>`**: Flow priority (higher = more priority)

### Flow Examples
```
# Immediate start
0->4 start 0 size 104857600

# Delayed start (500ms)  
1->5 start 500000 size 52428800

# Trigger-based start
2->6 trigger 1 size 104857600

# Flow with completion trigger
0->4 start 0 size 100000 send_done_trigger 1

# High priority flow
1->5 start 0 size 100000 prio 1
```

## Triggers System

### Trigger Types

#### 1. SingleShotTrigger (`oneshot`)
- **Behavior**: Fires once, activates ALL targets simultaneously
- **Use Case**: Sequential flow coordination
- **Implementation**: Once triggered, ignores further activations

```
trigger id 1 oneshot

0->1 start 0 size 100000 send_done_trigger 1
2->3 trigger 1 size 100000
```

#### 2. MultiShotTrigger (`multishot`)  
- **Behavior**: Fires multiple times, activates targets sequentially
- **Use Case**: Pipeline patterns, sequential activation
- **Implementation**: Each activation triggers next target in sequence

```
trigger id 1 multishot

0->1 start 0 size 100000 send_done_trigger 1
1->2 trigger 1 size 100000 send_done_trigger 1
2->3 trigger 1 size 100000
```

#### 3. BarrierTrigger (`barrier`)
- **Behavior**: Requires N activations before firing all targets
- **Use Case**: Synchronization, fan-in patterns
- **Implementation**: Counts activations, fires when threshold reached

```
trigger id 1 barrier count 3

0->7 start 0 size 100000 send_done_trigger 1
1->7 start 0 size 100000 send_done_trigger 1  
2->7 start 0 size 100000 send_done_trigger 1
3->4 trigger 1 size 100000    # Waits for all 3
```

### Trigger Syntax
```
trigger id <trigger_id> <type> [parameters]
```

#### Parameters
- **`id <number>`**: Unique trigger identifier (must be > 0)
- **`oneshot`**: Single-fire trigger
- **`multishot`**: Multi-fire sequential trigger
- **`barrier`**: Synchronization barrier
- **`count <N>`**: For barriers, number of activations needed

### Flow Completion Triggers
- **`send_done_trigger <id>`**: Fires when sender finishes transmission
- **`recv_done_trigger <id>`**: Fires when receiver completes reception

## Failures System

### Failure Types

HTSIM supports link failures at different network tiers:

#### Switch Types
- **`TOR`**: Top-of-Rack switches (Tier 0)
- **`AGG`**: Aggregation switches (Tier 1)  
- **`CORE`**: Core switches (Tier 2)

### Failure Syntax
```
failure switch_type <type> switch_id <id> link_id <link>
```

#### Parameters
- **`switch_type <TOR|AGG|CORE>`**: Which tier of switch
- **`switch_id <number>`**: Specific switch ID within tier
- **`link_id <number>`**: Specific link/port on that switch

### Failure Examples
```
# ToR uplink failure (reduces pod connectivity)
failure switch_type TOR switch_id 0 link_id 1

# Aggregation uplink failure (affects inter-pod traffic)
failure switch_type AGG switch_id 2 link_id 0

# Core switch failure (reduces inter-pod bandwidth)
failure switch_type CORE switch_id 1 link_id 3
```

### Failure Impact Analysis

#### ToR Switch Failures
- **Uplink failure**: Reduces connectivity to aggregation layer
- **Downlink failure**: Disconnects specific hosts
- **Effect**: Increased oversubscription, potential bottlenecks

#### Aggregation Switch Failures
- **Uplink failure**: Reduces pod's core connectivity
- **Downlink failure**: Affects specific ToR switches
- **Effect**: Degraded intra-pod and inter-pod communication

#### Core Switch Failures  
- **Effect**: Reduced inter-pod bandwidth, load redistribution

## Traffic Patterns

### Common Datacenter Patterns

#### 1. Incast (Many-to-One)
```
Nodes 8
Connections 4
Triggers 0
Failures 0

# Multiple senders to single receiver
0->7 start 0 size 50000000
1->7 start 0 size 50000000
2->7 start 0 size 50000000  
3->7 start 0 size 50000000
```

#### 2. All-to-All
```
Nodes 4
Connections 6
Triggers 0
Failures 0

0->1 start 0 size 10000000
0->2 start 100000 size 10000000
0->3 start 200000 size 10000000
1->2 start 300000 size 10000000
1->3 start 400000 size 10000000
2->3 start 500000 size 10000000
```

#### 3. MapReduce Pattern
```
Nodes 8
Connections 5
Triggers 1
Failures 0

trigger id 1 barrier count 4

# Map phase: parallel processing
0->4 start 0 size 25000000 send_done_trigger 1
1->4 start 0 size 25000000 send_done_trigger 1
2->4 start 0 size 25000000 send_done_trigger 1
3->4 start 0 size 25000000 send_done_trigger 1

# Reduce phase: waits for all map tasks
4->7 trigger 1 size 100000000
```

#### 4. Pipeline Pattern
```
Nodes 4
Connections 3
Triggers 1
Failures 0

trigger id 1 multishot

# Sequential processing pipeline
0->1 start 0 size 50000000 send_done_trigger 1
1->2 trigger 1 size 50000000 send_done_trigger 1
2->3 trigger 1 size 50000000
```

#### 5. Burst Traffic
```
Nodes 6
Connections 4
Triggers 2
Failures 0

trigger id 1 oneshot
trigger id 2 oneshot  

# Initial flow triggers burst
0->1 start 0 size 10000000 send_done_trigger 1

# Coordinated burst
2->3 trigger 1 size 100000000 send_done_trigger 2
4->5 trigger 1 size 100000000 send_done_trigger 2

# Cleanup flow
1->0 trigger 2 size 5000000
```

## Size and Timing Reference

### Data Size Conversions
| Unit | Bytes | Example Usage |
|------|-------|---------------|
| 1 KB | 1,024 | `size 1024` |
| 1 MB | 1,048,576 | `size 1048576` |
| 10 MB | 10,485,760 | `size 10485760` |
| 100 MB | 104,857,600 | `size 104857600` |
| 1 GB | 1,073,741,824 | `size 1073741824` |

### Time Conversions
| Unit | Microseconds | Example Usage |
|------|--------------|---------------|
| 1 ms | 1,000 | `start 1000` |
| 10 ms | 10,000 | `start 10000` |
| 100 ms | 100,000 | `start 100000` |
| 1 second | 1,000,000 | `start 1000000` |

## Advanced Examples

### Fault Tolerance Testing
```
Nodes 8
Connections 4
Triggers 1
Failures 2

# Simulate partial network failures
failure switch_type AGG switch_id 0 link_id 0
failure switch_type TOR switch_id 1 link_id 0

trigger id 1 barrier count 2

# Test robustness with failures
0->4 start 0 size 100000000 send_done_trigger 1
1->5 start 0 size 100000000 send_done_trigger 1

# Verify recovery capability
2->6 trigger 1 size 50000000
```

### Load Balancing Test
```
Nodes 8
Connections 6
Triggers 0
Failures 0

# Simultaneous cross-pod flows
0->4 start 0 size 104857600
1->5 start 0 size 104857600
2->6 start 0 size 104857600

# Same-pod flows for comparison
0->1 start 0 size 104857600
2->3 start 0 size 104857600
4->5 start 0 size 104857600
```

### Application Workflow Simulation
```
Nodes 12
Connections 8
Triggers 3
Failures 0

trigger id 1 barrier count 3  # Data gathering
trigger id 2 oneshot          # Processing 
trigger id 3 multishot        # Results distribution

# Data collection phase
0->9 start 0 size 50000000 send_done_trigger 1
1->9 start 0 size 50000000 send_done_trigger 1
2->9 start 0 size 50000000 send_done_trigger 1

# Processing phase
9->10 trigger 1 size 150000000 send_done_trigger 2

# Distribution phase  
10->3 trigger 2 size 30000000 send_done_trigger 3
10->4 trigger 3 size 30000000 send_done_trigger 3
10->5 trigger 3 size 30000000 send_done_trigger 3
10->6 trigger 3 size 30000000
```

## Best Practices

### File Organization
1. **Use comments** (`#`) to document flow purposes
2. **Group related flows** logically
3. **Define all triggers** before using them
4. **Specify failures** before flows for clarity

### Performance Considerations
1. **Large flows** (>100MB) show clearer performance differences
2. **Staggered start times** prevent artificial synchronization
3. **Realistic flow sizes** based on application requirements
4. **Consider network capacity** when sizing concurrent flows

### Debugging Tips
1. **Start simple** with single flows
2. **Verify node counts** match topology
3. **Check trigger IDs** are unique and properly referenced
4. **Validate failure parameters** against topology structure

## Error Messages

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "Mismatch in connection count" | Wrong Connections header | Count actual flows in file |
| "Trigger with no id" | Missing trigger ID | Add `id <number>` to trigger |
| "Unknown switch type" | Invalid switch_type | Use TOR, AGG, or CORE |
| "No start method specified" | Missing start time/trigger | Add `start <time>` or `trigger <id>` |
| "Trigger referenced but not specified" | Used undefined trigger | Define trigger before using |

## Integration with HTSIM

### Command Line Usage
```bash
# Run with traffic matrix file
./htsim_ndp -tm traffic_matrix.tm -topo topology.topo

# Run with stdin input
cat traffic_matrix.tm | ./htsim_ndp -topo topology.topo
```

### Output Analysis
- **Flow completion times**: Measure end-to-end latency
- **Throughput measurements**: Analyze bandwidth utilization  
- **Queue statistics**: Monitor congestion patterns
- **Failure recovery**: Observe adaptation to link failures

## Related Files

- **Topology files** (`.topo`): Define network structure
- **Log files**: Capture simulation results
- **Configuration files**: Set simulation parameters

This comprehensive guide covers all aspects of HTSIM traffic matrix files, enabling sophisticated network simulation scenarios and performance analysis.