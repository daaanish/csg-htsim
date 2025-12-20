# Simple Topology Creation Guide for HTSIM

## Overview: Nodes vs Switches

**Nodes** = Host computers that generate/receive traffic (endpoints)
**Switches** = Network devices that forward packets (ToR, aggregation, core)

In code:
- `NSRV` = number of server nodes (hosts)  
- `NTOR` = number of ToR switches
- `NAGG` = number of aggregation switches
- `NCORE` = number of core switches

## Method 1: Built-in Topologies (Easiest)

Let HTSIM auto-generate based on node count:

```bash
# 8-node, 2-tier leaf-spine topology
./htsim_ndp -nodes 8 -tiers 2 -linkspeed 1000 -tm myflows.txt

# 18-node, 3-tier fat-tree 
./htsim_ndp -nodes 18 -tiers 3 -linkspeed 10000 -tm myflows.txt
```

## Method 2: Custom Topology Files

Create `.topo` files for precise control:

### Example: 8-host leaf-spine
```
# File: my_topology.topo
nodes 8
tiers 2
podsize 8

tier 0  # ToR switches
downlink_speed_gbps 10
radix_up 2
radix_down 4
oversubscribed 2
switch_latency_ns 100
downlink_latency_ns 1000

tier 1  # Aggregation switches
downlink_speed_gbps 10
radix_down 2
switch_latency_ns 100
downlink_latency_ns 1000
```

### Key Parameters:
- `downlink_speed_gbps`: Physical link speed
- `radix_up/down`: Number of up/down ports per switch
- `oversubscribed`: Ratio for bandwidth matching
- `switch_latency_ns`: Processing delay
- `downlink_latency_ns`: Wire propagation delay

## Creating Traffic Flows

Traffic matrix format:
```
# File: flows.txt
Nodes 8
Connections 3
Triggers 0  
Failures 0

# src->dst start_time_us size_bytes [optional: id priority trigger]
0->4 start 0 size 104857600
1->5 start 1000 size 52428800
2->6 start 2000 size 26214400
```

### Flow Size Examples:
- 100 MB = 104,857,600 bytes
- 50 MB = 52,428,800 bytes
- 10 MB = 10,485,760 bytes
- 1 GB = 1,073,741,824 bytes

## Controlling Bandwidth

### 1. Physical Link Speed (Topology)
```
downlink_speed_gbps 10  # 10 Gbps links
```

### 2. Effective Rate (Runtime)
```bash
-linkspeed 1000  # 1000 Mbps pacing rate
```

### 3. Host NIC Rate (Compile-time)
Edit `sim/main.h`:
```cpp
#define HOST_NIC 10000  // 10 Gbps
```
Then `make clean && make`.

## Complete Working Example

### 1. Create topology (8 hosts, 2 tiers):
```bash
# Use built-in or create custom .topo file
```

### 2. Create traffic matrix:
```bash
cat > experiments/simple_examples/my_flows.txt << EOF
Nodes 8
Connections 2
Triggers 0
Failures 0

0->4 start 0 size 104857600
1->5 start 500000 size 52428800
EOF
```

### 3. Run simulation:
```bash
cd sim/datacenter
./htsim_ndp \\
  -nodes 8 \\
  -tm ../../experiments/simple_examples/my_flows.txt \\
  -linkspeed 1000 \\
  -q 50 \\
  -mtu 1500 \\
  -tiers 2 \\
  -strat ecmp \\
  -paths 2 \\
  -end 10000000 \\
  -o ../../experiments/simple_examples/results.log
```

### 4. Parse results:
```bash
cd ../..
./sim/parse_output experiments/simple_examples/results.log -ndp -show
```

## Key Parameters Reference

### Topology Control:
- `-nodes N`: Number of host endpoints
- `-tiers 2|3`: Leaf-spine (2) or fat-tree (3)  
- `-topo file.topo`: Custom topology file

### Traffic Control:
- `-tm file.txt`: Traffic matrix file
- `-conns N`: Auto-generate N permutation flows
- `-linkspeed Mbps`: Effective sending rate

### Performance Tuning:
- `-q N`: Queue size in packets
- `-mtu bytes`: Packet size (default 1500)
- `-end microseconds`: Simulation duration

### Routing Strategy:
- `-strat single`: Single path per flow
- `-strat ecmp`: Equal-cost multipath
- `-strat rand`: Random path selection
- `-paths N`: Number of paths to use

## Quick Tests

### Test 1: Simple 2-flow competition
```bash
# Terminal command:
./experiments/simple_examples/run_simple_working.sh
```

### Test 2: Many-to-one incast
```bash
# Create incast traffic matrix:
cat > experiments/simple_examples/incast.txt << EOF
Nodes 8
Connections 7
Triggers 0
Failures 0

0->7 start 0 size 10485760
1->7 start 0 size 10485760
2->7 start 0 size 10485760
3->7 start 0 size 10485760
4->7 start 0 size 10485760
5->7 start 0 size 10485760
6->7 start 0 size 10485760
EOF

# Run:
cd sim/datacenter && ./htsim_ndp -nodes 8 -tm ../../experiments/simple_examples/incast.txt -linkspeed 1000 -end 5000000 -o ../../experiments/simple_examples/incast_results.log
```

### Test 3: Varying link speeds
```bash
# Low speed: 100 Mbps
./htsim_ndp -nodes 8 -tm flows.txt -linkspeed 100 

# High speed: 10 Gbps  
./htsim_ndp -nodes 8 -tm flows.txt -linkspeed 10000
```

## Troubleshooting

- **Assertion errors**: Try `-strat ecmp` instead of `single`
- **"Route Strategy not set"**: Add `-strat ecmp` or `-strat single`
- **"Linkspeed 0Gbps"**: Normal for rates < 500 Mbps (rounding)
- **Segfaults**: Ensure traffic matrix node count matches `-nodes`
- **No output**: Check simulation `-end` time is sufficient

## Output Analysis

The log contains:
- Flow completion times and throughput
- Queue utilization  
- Packet counts (new/retransmitted/bounced)

Use `parse_output` tool for summaries:
```bash
./sim/parse_output results.log -ndp -show
```