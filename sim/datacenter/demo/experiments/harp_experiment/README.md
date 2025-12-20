# HARP Traffic Matrix Experiment for HTSIM

This experiment uses the **htsim_cbr** simulator to run HARP traffic matrices on the Abilene topology, with support for traffic engineering via Gurobi-computed optimal routing.

## HTSIM Features Implemented

- **CBR (constant bit-rate) driver** for simulating UDP-like sending mechanics
- **Arbitrary topologies** read from JSON files
- **Traffic engineering mechanics:**
  - Enumerating and listing **k-shortest paths** per s-d pair
  - Ability to **pin a flow** to a specific path
  - Custom **split ratios** for flows across paths
  - **Explicit path specification** for each flow
- **Demand matrix support** (CSVs → HTSIM TMs):
  - **Discrete**: Each TM runs separately in a new HTSIM instance
  - **Continuous**: All TMs in a single traffic file with different start times (flows may overlap)

---

## Directory Structure

```
harp_experiment/
├── abilene_harp.json           # Abilene topology (12 nodes, 15 links)
├── config.json                 # Experiment configuration

# Core scripts
├── run_experiment.py           # Run single/batch TMs (discrete mode)
├── run_all_tm_experiment.py    # MLU vs Loss experiment (discrete)
├── run_overlapping_experiment.py # Continuous overlapping TMs experiment
├── run_continuous_experiment.py # Generate combined TM files

# Utilities
├── csv_to_tm.py                # CSV → .tm converter with split ratio support
├── compute_mlu.py              # MLU computation utilities
├── plot_exp4_comparison.py     # Comparison plots
├── run_loss_vs_time.py         # Loss vs time analysis
├── tm_breakdown.py             # If you have a single HARP-obtained CSV from the HARP repo this can break it down to individual TMs

# Data
├── firebolt_dl/                # Gurobi optimal split ratios
│   ├── abilene_4_paths/        # split_ratios_snapshot_{tm_id}.npy
│   └── abilene_4_paths_dict_cluster_0.pkl
├── harp_csvs/                  # ~48K traffic matrix CSVs

# Results
├── exp1_default_routing/       # Discrete, default ECMP routing
├── exp3_explicit_routes/       # Discrete, Gurobi optimal explicit paths
├── exp4_optimal_55s/           # Continuous overlapping experiment
```

---

## Experiments

### Experiment 1: Discrete TMs with Default Routing
Each TM runs independently. Default ECMP routing (single random path per flow).

```bash
python3 run_all_tm_experiment.py --all --duration 10 --output-dir exp1_default_routing
```

**Result**: 0% loss for all TMs (no overlap, low MLU)

### Experiment 3: Discrete TMs with Gurobi Optimal Routing
Each TM runs independently with Gurobi-computed explicit paths and split ratios.

```bash
python3 run_all_tm_experiment.py --all --duration 10 \
  --split-ratios-dir firebolt_dl/abilene_4_paths \
  --pairs-dict firebolt_dl/abilene_4_paths_dict_cluster_0.pkl \
  --output-dir exp3_explicit_routes
```

**Result**: 0% loss (optimal routing minimizes congestion for each TM)

### Experiment 4: Continuous Overlapping TMs
Multiple TMs run in a single simulation with 5-second intervals (HARP period). Flows from different TMs overlap, revealing congestion hidden in discrete experiments.

```bash
# Run with optimal routing, 10 TMs, 55 seconds
python3 run_overlapping_experiment.py --mode optimal --max-tms 10 --end-time 55

# Run loss vs time analysis (multiple time points)
python3 run_loss_vs_time.py
```

**Result**: ~12-16% loss due to TM overlap (vs 0% in discrete experiments)

---

## Simulation Parameters

| Parameter | Value |
|-----------|-------|
| **Topology** | Abilene (12 nodes, 15 links) |
| **Link Speed** | 10 Gbps |
| **Flow Size** | 100 MB per micro-flow |
| **Sending Rate** | 1 Mbps per micro-flow |
| **TM Interval** | 5 seconds (HARP period) |
| **Queue Size** | 22 KB |

### Quantized Rate Aggregation (QRA)
HTSIM uses a single global sending rate. To model variable demands:
- `k = ceil(demand_mbps / base_rate_mbps)` parallel micro-flows
- Aggregate throughput ≈ `k × base_rate`

---

## Key Scripts

### run_experiment.py
Run single or batch TMs in discrete mode.
```bash
python3 run_experiment.py --tm-ids 1 2 3 --duration 10
```

### run_overlapping_experiment.py
Run continuous overlapping TM experiment.
```bash
python3 run_overlapping_experiment.py \
  --mode optimal|default \
  --max-tms 10 \
  --end-time 55 \
  --output-dir exp4_optimal_55s
```

### analysis.ipynb
Jupyter notebook with plotting and analysis functions for visualizing experiment results.

---

## Output Files

| File | Description |
|------|-------------|
| `mlu_vs_loss_results.csv` | Per-TM metrics (MLU, loss rate, goodput) |
| `results/summary.csv` | Per-TM summary from discrete experiments |
| `exp4_loss_rate_slide.png` | Loss vs time plot |

---

## Reproducing Experiments

The experiment output directories (`exp1_*`, `exp3_*`, `exp4_*`) are not included in the repository. To regenerate them:

### Exp1: Discrete Default Routing (takes ~4 hours for all 2000 TMs)
```bash
python3 run_all_tm_experiment.py --all --duration 10 --output-dir exp1_default_routing
```

### Exp3: Discrete Gurobi Optimal Routing, 2000 TMs
```bash
python3 run_all_tm_experiment.py --all --duration 10 \
  --split-ratios-dir firebolt_dl/abilene_4_paths \
  --pairs-dict firebolt_dl/abilene_4_paths_dict_cluster_0.pkl \
  --output-dir exp3_explicit_routes
```

### Exp4: Continuous Overlapping TMs (quick test)
```bash
# 10 TMs, 55 seconds (~1 minute)
python3 run_overlapping_experiment.py --mode optimal --max-tms 10 --end-time 55 \
  --output-dir exp4_optimal_55s
```

### Required Data (not in repo due to size)
- `harp_csvs/` - HARP traffic matrix CSVs (~48K files, 191MB)

---

## Topology

Abilene network: 12 nodes (r1-r12 → indices 0-11), 15 bidirectional links, ~10 Gbps link capacity.

