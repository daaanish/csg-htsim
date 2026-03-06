# GEANT Experiment — Setup Guide

22-node, 36-link topology based on the GÉANT European research network.

---

## Files

| File | Description |
|------|-------------|
| `topo/geant.txt` | Original topology (1-indexed, kbps) |
| `topo/geant.json` | htsim JSON topology (r1–r22, Mbps) |

Node mapping: `geant.txt` node **N** = `geant.json` host **rN** = htsim index **N−1**

---

## Input Files Needed

### 1. Topology — `topo/geant.json` ✅

### 2. Traffic Matrix (`.tm` file)

Each connection line:
```
<src>-><dst>  id <N> start <ps> demand <bytes> admitted <bytes> rate <Mbps> <routing>
```

**Key tokens:**

| Token | Description |
|-------|-------------|
| `demand` | Total application demand in bytes (metadata for telemetry) |
| `admitted` | Bytes to actually send (overrides `size`) |
| `rate` | Per-flow CBR sending rate (Mbps) |
| `paths_idx` | Pin to K-shortest path index, e.g. `0` or `0,1` |
| `split` | Split ratios across paths, e.g. `0.6,0.4` |
| `explicit_routes` | Exact queue chains from solver, e.g. `q_r1_r3\|q_r3_r7;q_r1_r5\|q_r5_r7` |
| `thresholds` | Byte thresholds for deterministic path switching |

**Example TM for GEANT:**
```
Nodes 22
Connections 2
0->21 id 1 start 0 demand 50000000 admitted 40000000 rate 800 paths_idx 0
0->21 id 2 start 0 demand 50000000 admitted 30000000 rate 600 paths_idx 1
```

### 3. (Optional) Config for `generate_te_tm.py`

Auto-generates `.tm` files with threshold-based demand splitting. Each pair has:
- **D_st** — total application demand
- **threshold** — per-pair cutoff between base and overflow regimes
- **W1** — how to split traffic ≤ threshold across paths
- **W2** — how to split traffic > threshold across paths (weights < 1.0 means not all overflow is admitted)

```
base     = min(D_st, threshold)
overflow = max(0, D_st - threshold)
per_path_bytes = W1[p] * base + W2[p] * overflow
B_st (admitted) = Σ per_path_bytes
```

```json
{
    "nodes": 22,
    "threshold": 25000000,
    "default_rate_mbps": 200,
    "start_time_ps": 0,
    "pairs": [
        {"src": 0, "dst": 21, "D_st": 50000000, "threshold": 30000000,
         "W1": {"weights": [0.6, 0.4], "path_indices": [0, 1]},
         "W2": {"weights": [0.3, 0.1], "path_indices": [0, 1]}},

        {"src": 1, "dst": 10, "D_st": 20000000, "threshold": 15000000,
         "W1": {"weights": [1.0], "path_indices": [0]},
         "W2": {"weights": [0.5], "path_indices": [0]}}
    ]
}
```

Each pair can override `threshold` and `rate_mbps`. The top-level values are just defaults.

---

## Routing Choices (pick one per flow)

| Mode | TM tokens | Use case |
|------|-----------|----------|
| Default shortest path | _(none)_ | Baseline / ECMP |
| K-shortest path index | `paths_idx 0,1` + `split 0.6,0.4` | Select from enumerated paths, probabilistic split |
| Explicit solver routes | `explicit_routes q_r1_r3\|q_r3_r7;q_r1_r5\|q_r5_r7` | Gurobi / LP solver output |
| Threshold switching | `paths 3 thresholds 200000,600000` | Deterministic byte-level splitting |

### Threshold switching — path selection & examples

Paths come from K-shortest (auto or explicit via `paths_idx`).

**Example 1 — Auto path selection, 3 paths:**
```
# Picks the 3 shortest paths from r1→r22 automatically
0->21 start 0 admitted 1000000 paths 3 thresholds 200000,600000
```
- Bytes 0–199,999 → shortest path
- Bytes 200,000–599,999 → 2nd shortest
- Bytes 600,000+ → 3rd shortest

**Example 2 — Manual path indices:**
```
# Use list_kshort to find indices first, then cherry-pick paths 0, 2, 4
0->21 start 0 admitted 1000000 paths_idx 0,2,4 thresholds 200000,600000
```
- Bytes 0–199,999 → path index 0
- Bytes 200,000–599,999 → path index 2
- Bytes 600,000+ → path index 4

**Example 3 — Simple 2-path split at 500 KB:**
```
0->21 start 0 admitted 2000000 paths 2 thresholds 500000
```
- Bytes 0–499,999 → path 0
- Bytes 500,000+ → path 1

**Example 4 — With demand/admitted TE metadata:**
```
0->21 id 1 start 0 demand 5000000 admitted 3000000 rate 500 paths 2 thresholds 1500000
```
- Total demand = 5 MB, but only 3 MB admitted
- First 1.5 MB on path 0, remaining 1.5 MB on path 1
- Sends at 500 Mbps

**Example 5 — Explicit routes + thresholds:**
```
0->21 start 0 admitted 1000000 explicit_routes q_r1_r16|q_r16_r22;q_r1_r5|q_r5_r19|q_r19_r22 thresholds 400000
```
- Bytes 0–399,999 → solver route A (r1→r16→r22)
- Bytes 400,000+ → solver route B (r1→r5→r19→r22)

**Example 6 — Uneven 4-path split:**
```
0->21 start 0 admitted 10000000 paths 4 thresholds 1000000,3000000,7000000
```
- Bytes 0–999,999 (1 MB) → path 0
- Bytes 1,000,000–2,999,999 (2 MB) → path 1
- Bytes 3,000,000–6,999,999 (4 MB) → path 2
- Bytes 7,000,000+ (3 MB) → path 3

> Number of thresholds = number of paths − 1

**Threshold vs split:** Thresholds switch paths **deterministically** by byte count. `split` distributes packets **probabilistically** by ratio. Both can be combined with `paths_idx` or `explicit_routes`.

---

## Commands

### Inspect topology & paths
```bash
# List host names and indices
./sim/datacenter/htsim_cbr -json_topo experiments/geant-exp/topo/geant.json -list_hosts

# K-shortest paths between two nodes
./sim/datacenter/htsim_cbr -json_topo experiments/geant-exp/topo/geant.json -list_kshort_names r1 r22 5
```

### Generate TM (optional helper)
```bash
python3 experiments/te_demand_admitted/generate_te_tm.py \
    --config my_config.json -o my_traffic.tm
```

### Run simulation
```bash
./sim/datacenter/htsim_cbr \
    -json_topo experiments/geant-exp/topo/geant.json \
    -tm my_traffic.tm \
    -end 10.0 \
    -o results.dat
```

### Extract telemetry
```bash
./sim/datacenter/htsim_cbr ... 2>&1 | grep 'GLOBAL_STATS'
```

---

## Telemetry Output

Three levels printed to stdout after simulation:

| Level | Example |
|-------|---------|
| `FLOW_STATS` | Per-flow: `demand_bytes`, `admitted_bytes`, `delivered_bytes`, `delivery_ratio` |
| `PAIR_STATS` | Per src→dst pair (aggregated) |
| `GLOBAL_STATS` | Network-wide totals |

Key metric: `delivery_ratio = delivered_bytes / admitted_bytes`

---

## Link Speed Tiers

| Speed | Mbps | Links |
|-------|------|-------|
| 10 Gbps backbone | 10000 | 19 links |
| 2.4 Gbps mid-tier | 2400 | 13 links |
| 155 Mbps low-cap | 155 | 4 links |

All links are full-duplex (bidirectional) by default.
