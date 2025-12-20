# HTSIM Notes

## HARP Traffic Engineering Experiments

This section documents the HARP-TE experiments using HTSIM-CBR for simulating traffic matrices on the Abilene network with Traffic Engineering.

### Overview

We extended HTSIM with:
- **CBR (constant bit-rate) driver** (`main_cbr.cpp`) for UDP-like sending mechanics
- **JSON topology support** (`JsonTopology` class) for arbitrary network structures
- **Traffic engineering features:**
  - K-shortest path enumeration per source-destination pair
  - Per-flow path pinning via `path_indices`
  - Split ratios across multiple paths via `split` token
  - Explicit path specification via `explicit_routes` (Gurobi's actual paths)

### Key Files

| File | Description |
|------|-------------|
| `sim/datacenter/main_cbr.cpp` | CBR simulator entry point with JSON topology and TE support |
| `sim/datacenter/fat_tree_topology.cpp` | Extended with `JsonTopology` class |
| `sim/datacenter/demo/experiments/harp_experiment/` | HARP experiment scripts |
| `sim/datacenter/demo/topo/abilene_harp.json` | Abilene network topology (12 nodes) |

### Experiment Scripts

| Script | Purpose |
|--------|---------|
| `run_experiment.py` | Run single/batch TMs in discrete mode |
| `run_all_tm_experiment.py` | Run all 2000 TMs, compare MLU vs loss |
| `run_overlapping_experiment.py` | Run TMs continuously with overlap |
| `csv_to_tm.py` | Convert HARP CSVs to HTSIM TM format |
| `compute_mlu.py` | Calculate Maximum Link Utilization |
| `analysis.ipynb` | Jupyter notebook for plotting results |

### How to Run

```bash
# Build the CBR simulator
cd sim/datacenter
make htsim_cbr

# Run discrete experiment (one TM at a time)
cd demo/experiments/harp_experiment
python3 run_experiment.py --tm-ids 1 --duration 10

# Run discrete experiment with Gurobi optimal routing
python3 run_all_tm_experiment.py --sample 20 --duration 10 \
  --split-ratios-dir firebolt_dl/abilene_4_paths \
  --pairs-dict firebolt_dl/abilene_4_paths_dict_cluster_0.pkl

# Run continuous overlapping experiment (10 TMs, 55 seconds)
python3 run_overlapping_experiment.py --mode optimal --max-tms 10 --end-time 55
```

### TM File Format (with TE extensions)

```
# Basic flow
0->1 start 0 size 100000000

# Flow with explicit paths and split ratios (Gurobi optimal)
0->5 start 0 size 100000000 explicit_routes q_r1_r2,q_r2_r6|q_r1_r3,q_r3_r6 split 0.7,0.3
```

Gurobi optimal paths as well as all the traffic matrices can be found by following the instructions in the HARP github repository.

### Key Results

1. **Discrete experiments** (one TM at a time): 0% loss for both default and optimal routing
2. **Continuous overlapping experiments**: ~12-16% loss due to TM overlap
3. **Per-TM optimal routing fails under overlap** - routes optimized for individual TMs conflict when combined

---
