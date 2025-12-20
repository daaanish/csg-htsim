# Simple HTSIM Examples

This directory contains simple examples for getting started with HTSIM network simulation.

## Files Overview

### Documentation
- `TOPOLOGY_GUIDE.md` - Complete guide for creating topologies and running simulations

### Topology Files
- `topos/simple_4host.topo` - 4-host, 2-tier leaf-spine topology
- `topos/leaf_spine_2hosts_1tor.topo` - Minimal 2-host topology (bundled)
- `topos/leaf_spine_2hosts_minimal.topo` - Ultra-minimal 2-host topology (single uplinks)

### Traffic Matrices
- `tm_4host_2flows.txt` - 2 flows for 4-node topology
- `tm_8host_2flows.txt` - 2 flows for 8-node topology

### Run Scripts
- `run_simple_working.sh` - Working 8-node example with 2 flows
- `run_simple_4host.sh` - 4-node example (may have routing issues)

### Visualization Tools
- `analyze_topology.sh` - Complete topology analysis (structure + flow paths)
- `visualize_topology.sh` - Shows topology structure and switch layout
- `trace_flow_path.sh` - Traces specific flow paths through the network

### Log Files
- `simple_working_results.log` - Output from working example
- `simple_4host_results.log` - Output from 4-host example

## Quick Start

1. **Visualize a topology:**
   ```bash
   ./experiments/simple_examples/analyze_topology.sh -nodes 8 -tiers 2
   ```

2. **Run the working example:**
   ```bash
   ./experiments/simple_examples/run_simple_working.sh
   ```

3. **Trace a specific flow path:**
   ```bash
   ./experiments/simple_examples/trace_flow_path.sh 0 4 -nodes 8 -tiers 2
   ```

2. **Create your own traffic matrix:**
   ```bash
   # Edit tm_8host_2flows.txt or create new file
   # Format: src->dst start time_us size bytes
   ```

3. **Customize parameters:**
   - Change `-linkspeed` for different bandwidth
   - Adjust `-end` for simulation duration  
   - Modify `-q` for queue sizes
   - Use `-strat ecmp` for multipath routing

## Example Commands

```bash
# From project root directory:

# Basic 8-node simulation
cd sim/datacenter
./htsim_ndp -nodes 8 -tm ../../experiments/simple_examples/tm_8host_2flows.txt -linkspeed 1000 -strat ecmp -paths 2 -end 10000000

# With custom topology
./htsim_ndp -nodes 4 -topo ../../experiments/simple_examples/topos/simple_4host.topo -tm ../../experiments/simple_examples/tm_4host_2flows.txt -linkspeed 1000

# Parse results
cd ../..
./sim/parse_output experiments/simple_examples/simple_working_results.log -ndp -show
```

## Common Issues

- **Assertion failures**: Use `-strat ecmp` instead of `-strat single` for small topologies
- **Segmentation faults**: Ensure traffic matrix node count matches `-nodes` parameter
- **Route errors**: Add oversubscription ratios to topology files when using single uplinks

See `TOPOLOGY_GUIDE.md` for detailed troubleshooting and advanced usage.