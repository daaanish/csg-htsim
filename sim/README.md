# HTSIM - High-Throughput Simulator

A packet-level network simulator for datacenter networks, with support for CBR (constant bit-rate) traffic, arbitrary JSON topologies, and traffic engineering.

## Features

- **CBR driver** for UDP-like sending mechanics
- **JSON topology support** for arbitrary network structures
- **Traffic engineering:**
  - K-shortest path enumeration
  - Per-flow path pinning
  - Split ratios across paths
  - Explicit path specification
- **Traffic matrix support** (CSV → HTSIM TM format)

## Quick Start

### Build

```bash
cd sim/datacenter
make htsim_cbr
```

### Run a Simple Simulation

```bash
./htsim_cbr -json_topo topologies/example.json -tm traffic_matrices/example.tm -end 10
```

### Run HARP Experiments

See `demo/experiments/harp_experiment/README.md` for detailed instructions on running traffic matrix experiments with Gurobi-optimal routing.

```bash
cd demo/experiments/harp_experiment
python3 run_experiment.py --tm-ids 1 --duration 10
```

## Directory Structure

```
sim/
├── *.cpp, *.h          # Core HTSIM library
├── Makefile            # Build configuration
├── datacenter/         # Datacenter-specific code
│   ├── main_cbr.cpp    # CBR simulator entry point
│   ├── topologies/     # Example topology files
│   ├── traffic_matrices/ # Example TM files
│   └── demo/experiments/harp_experiment/  # HARP experiments
├── EXAMPLES/           # Example simulations
└── tests/              # Test cases
```

## Requirements

- C++ compiler (g++ recommended)
- Python 3.x (for experiment scripts)
- NumPy, Matplotlib (for analysis)

## Building

```bash
# Build all binaries
make

# Build CBR simulator only
make htsim_cbr

# Clean build artifacts
make clean
```

## License

See original HTSIM repository for license information.