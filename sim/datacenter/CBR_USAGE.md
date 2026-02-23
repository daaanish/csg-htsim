# HTSIM CBR & Traffic Engineering — Usage Guide

Complete reference for the `htsim_cbr` binary: command-line options, traffic
matrix format, multipath modes, traffic-engineering extensions, path listing
utilities, and worked examples.

---

## Table of Contents

1. [Building](#building)
2. [Quick Start](#quick-start)
3. [Command-Line Options](#command-line-options)
4. [Topology Modes](#topology-modes)
5. [Traffic Matrix (.tm) Format](#traffic-matrix-tm-format)
6. [Multipath Modes](#multipath-modes)
7. [Traffic Engineering (demand / admitted)](#traffic-engineering-demand--admitted)
8. [Path Listing & Inspection](#path-listing--inspection)
9. [Queue Logging](#queue-logging)
10. [Post-Simulation Telemetry](#post-simulation-telemetry)
11. [Worked Examples](#worked-examples)

---

## Building

```bash
cd sim/datacenter
make htsim_cbr
```

The binary is placed at `sim/datacenter/htsim_cbr`.

---

## Quick Start

```bash
# 8-node 2-tier fat-tree, default permutation traffic, 1 Gbps CBR, 1 second
./htsim_cbr -nodes 8 -tiers 2 -rate 1000 -end 1.0

# Load a TM file on a 3-tier fat-tree
./htsim_cbr -nodes 54 -tiers 3 -tm traffic_matrices/abilene_two_flows.tm \
            -rate 500 -end 0.5 -o my_run.dat

# JSON topology
./htsim_cbr -json_topo ../topologies/abilene.json \
            -tm traffic_matrices/abilene_two_flows.tm -rate 100 -end 1.0
```

---

## Command-Line Options

### Output & Topology

| Flag | Args | Default | Description |
|------|------|---------|-------------|
| `-o` | `<file>` | `logout.dat` | Output log filename |
| `-nodes` | `<N>` | `8` | Number of servers (fat-tree mode) |
| `-tiers` | `2\|3` | `2` | Fat-tree tiers (2 or 3) |
| `-json_topo` | `<file>` | — | Use an arbitrary JSON graph topology instead of fat-tree |
| `-tm` | `<file>` | — | Traffic matrix file. If omitted, a random permutation is used |

### Simulation Parameters

| Flag | Args | Default | Description |
|------|------|---------|-------------|
| `-rate` | `<Mbps>` | `1000` | Default CBR sending rate per flow (overridden by per-flow `rate` in TM) |
| `-linkspeed` / `-fabric_mbps` | `<Mbps>` | `5000` | Fabric (inter-switch) link speed |
| `-host_nic_mbps` | `<Mbps>` | `HOST_NIC` | Host NIC speed |
| `-q` | `<pkts>` | `15` | Queue size in packets |
| `-end` | `<sec>` | `1.01` | Simulation end time in seconds |
| `-seed` | `<int>` | `time(NULL)` | RNG seed (0 = use wall-clock) |
| `-hop_latency` | `<us>` | `1` | Per-hop propagation latency in microseconds |
| `-switch_latency` | `<us>` | `0` | Per-switch processing latency in microseconds |

### Routing & Multipath

| Flag | Args | Default | Description |
|------|------|---------|-------------|
| `-strat` | `rand\|perm\|single\|ecmp` | `rand` | Route strategy: random, permutation, single-path, or ECMP |
| `-multipath` | — | off | Enable multipath for all flows (even those without TM multipath tokens) |
| `-paths` | `<N>` | `3` | Default number of ECMP paths per flow (overridden by per-flow `paths` in TM) |
| `-single_path_index` | `<idx>` | `-1` | Force all single-path flows to use this ECMP path index |
| `-split` | `<r1,r2,...>` | equal | Default comma-separated split ratios (auto-normalized). Overridden by per-flow `split` in TM |

### Queue Configuration

| Flag | Args | Default | Description |
|------|------|---------|-------------|
| `-queue_type` | `<type>` | `composite` | Queue discipline. Options: `random`, `composite`, `ecn`, `composite_ecn`, `lossless`, `lossless_input`, `lossless_input_ecn`, `ecn_prio`, `priority` |
| `-queue_log` | `<mode>` | `none` | Queue logging mode: `none`, `simple`, `sampling`, `empty` |
| `-queue_period_us` | `<us>` | `10` | Sampling period for `sampling`/`empty` queue loggers |

### Path Listing (print-and-exit)

| Flag | Args | Description |
|------|------|-------------|
| `-list_paths` | `<src> <dst>` | Print all ECMP paths between two hosts, then exit |
| `-list_kshort` | `<src> <dst> <K>` | Print K-shortest paths between two hosts (by index), then exit |
| `-list_kshort_names` | `<srcName> <dstName> <K>` | Same as above but using host names (JSON topo only) |
| `-list_hosts` | — | Print host index↔name mapping (JSON topo only), then exit |

---

## Topology Modes

### Fat-Tree

The default mode. Specify `-nodes` and `-tiers`:

```bash
# 2-tier with 8 servers
./htsim_cbr -nodes 8 -tiers 2 -rate 500 -end 1.0

# 3-tier with 54 servers
./htsim_cbr -nodes 54 -tiers 3 -rate 500 -end 1.0
```

Custom link speeds (overrides the default 5 Gbps fabric):

```bash
./htsim_cbr -nodes 8 -tiers 2 -fabric_mbps 10000 -host_nic_mbps 10000
```

### JSON Graph Topology

For arbitrary topologies (e.g., Abilene, campus networks), supply a JSON file:

```bash
./htsim_cbr -json_topo topologies/abilene.json -tm traffic_matrices/abilene_single.tm
```

JSON topologies support:
- BFS shortest-path routing
- Yen's K-shortest paths (`-list_kshort`, per-flow `paths_idx`)
- Explicit Gurobi routes (`explicit_routes` in TM)
- Named hosts (`-list_hosts`, `-list_kshort_names`)

---

## Traffic Matrix (.tm) Format

A `.tm` file has a header section followed by connection, trigger, and failure
definitions.

### Header

```
Nodes <N>
Connections <C>
Triggers <T>        # optional, default 0
Failures <F>        # optional, default 0
```

Lines starting with `#` are comments and are ignored.

### Connection Lines

```
<src>-><dst>  <token> <value>  [<token> <value> ...]
```

All tokens are optional except that every connection must have either a `start`
time or a `trigger`.

| Token | Value | Description |
|-------|-------|-------------|
| `start` | `<picoseconds>` | Flow start time (in picoseconds) |
| `size` | `<bytes>` | Total bytes to send (0 or omitted = unlimited) |
| `id` | `<int>` | Unique flow identifier (must be > 0 if triggers are used) |
| `rate` | `<Mbps>` | Per-flow CBR rate override (overrides CLI `-rate`) |
| `paths` | `<N>` | Number of ECMP paths to use (≥2 enables multipath) |
| `split` | `<r1,r2,...>` | Comma-separated split ratios (auto-normalized to sum=1.0) |
| `paths_idx` | `<i1,i2,...>` | Comma-separated ECMP path indices (0-based) to select |
| `thresholds` | `<b1,b2,...>` | Comma-separated byte thresholds for deterministic path switching |
| `explicit_routes` | `<route1;route2>` | Semicolon-separated explicit routes; each route is pipe-separated queue names (e.g., `q_r1_r2\|q_r2_r5;q_r1_r3\|q_r3_r5`) |
| `demand` | `<bytes>` | d_st: total application demand — metadata for TE reporting |
| `admitted` | `<bytes>` | b_st: admitted volume from TE solver — overrides `size` as the active flow size |
| `trigger` | `<trigger_id>` | Start this flow when the named trigger fires (replaces `start`) |
| `send_done_trigger` | `<trigger_id>` | Fire this trigger when all bytes are sent |
| `recv_done_trigger` | `<trigger_id>` | Fire this trigger when all bytes are received |
| `prio` | `<int>` | Priority value (lower = higher priority, default 2000000) |

### Trigger Lines

```
trigger id <N> <type> [count <C>]
```

| Type | Description |
|------|-------------|
| `oneshot` | Fires once when activated |
| `multishot` | Fires every time it is activated |
| `barrier` | Fires when `count` prerequisite events have occurred |

Triggers referenced by flows are auto-created as placeholders and merged with
the explicit trigger definition. Trigger IDs must be > 0.

### Failure Lines

```
failure switch_type <TOR|AGG|CORE> switch_id <N> link_id <N>
```

Used to simulate link failures in fat-tree topologies.

---

## Multipath Modes

### 1. Probabilistic Split Ratios (default multipath mode)

Each packet is routed to one of N paths using weighted-random selection.

**Via CLI (applies to all flows):**

```bash
./htsim_cbr -nodes 8 -tiers 2 -tm my.tm -multipath -paths 3 -split 0.5,0.3,0.2
```

**Via TM (per-flow):**

```
0->7 start 0 paths 3 split 0.5,0.3,0.2
```

Split ratios are auto-normalized. If not provided, traffic is distributed
equally among paths.

Priority: per-flow TM `split` > CLI `-split` > equal distribution.

### 2. Byte-Threshold Switching (deterministic)

Traffic is sent on path 0 until a byte threshold is reached, then switches to
path 1, and so on. This is a deterministic split, not probabilistic.

**Via TM only:**

```
0->7 start 0 paths 3 thresholds 100000,500000
```

This means:
- Bytes 0–99,999 → path 0
- Bytes 100,000–499,999 → path 1
- Bytes 500,000+ → path 2

The number of thresholds should be (number of paths − 1).

### 3. Explicit Gurobi Routes

Bypass the K-shortest-path computation entirely by specifying routes as
sequences of queue names from an offline solver (e.g., Gurobi). Requires
JSON topology.

**Via TM only:**

```
0->7 start 0 explicit_routes q_r1_r2|q_r2_r5|q_r5_r7;q_r1_r3|q_r3_r7
```

- `;` separates alternative paths
- `|` separates queues within a path
- Queue names must match those in the JSON topology

**Discovering queue names:** Use the path-listing commands to find the exact
queue names used by your JSON topology. The output prints each route as
pipe-separated queue names — the same format `explicit_routes` expects.

```bash
# Step 1: Look up host names / indices
./htsim_cbr -json_topo topologies/abilene.json -list_hosts

# Step 2: List K-shortest paths to see available routes and their queue names
./htsim_cbr -json_topo topologies/abilene.json -list_kshort 1 9 5
# or by host name:
./htsim_cbr -json_topo topologies/abilene.json -list_kshort_names r2 r10 5
```

Example output:

```
Top-5 shortest paths from host 1 to host 9:
Index : Path (queue hops)
[0] q_r2_r3 | q_r3_r10
[1] q_r2_r4 | q_r4_r10
[2] q_r2_r3 | q_r3_r6 | q_r6_r10
...
```

To use paths 0 and 1 in your TM, copy the queue names and join with `;`:

```
1->9 start 0 explicit_routes q_r2_r3|q_r3_r10;q_r2_r4|q_r4_r10
```

The workflow is: run `-list_kshort` → pick the routes your solver selected →
paste the queue names into `explicit_routes`.

### 4. Explicit Path Indices

Select specific paths from the ECMP (or K-shortest) path set by index:

**Via TM:**

```
0->8 start 0 paths 2 paths_idx 0,3
```

Use `-list_paths` or `-list_kshort` to discover available indices.

### Priority of Path Count (`paths`)

Per-flow TM `paths` > CLI `-paths` > default (min(3, available)).

### Enabling Multipath

Multipath is automatically enabled for any flow that specifies `paths ≥ 2`,
`split`, `thresholds`, or `explicit_routes`. The CLI `-multipath` flag enables
it globally for all flows (even those without those tokens).

---

## Traffic Engineering (demand / admitted)

For integration with an offline traffic-engineering solver:

| TM Token | Meaning |
|----------|---------|
| `demand` | d_st — total application-layer demand in bytes. Metadata only; does not affect simulation. |
| `admitted` | b_st — admitted traffic volume from the TE solver in bytes. **When > 0, becomes the active flow-size** (overrides `size`). The CBR source will stop after sending this many bytes. |
| `rate` | Per-flow sending rate in Mbps. Overrides the CLI `-rate` default. |

### Workflow

1. Run your TE solver (e.g., Gurobi LP) to get per-flow admitted volumes, path
   assignments, and split ratios.
2. Generate a `.tm` file with `demand`, `admitted`, `rate`, and routing info.
3. Run the simulation.
4. Parse the FLOW_STATS / PAIR_STATS / GLOBAL_STATS telemetry output.

### Example TM

```
Nodes 8
Connections 3

0->7 id 1 start 0 demand 50000000 admitted 40000000 rate 800 paths 2 split 0.6,0.4
1->6 id 2 start 0 demand 30000000 admitted 20000000
2->5 id 3 start 0 demand 10000000 admitted 10000000 rate 500 paths 2 split 0.5,0.5
```

---

## Path Listing & Inspection

These modes build the topology, print path information, and exit immediately
(no simulation is run).

### List all ECMP paths between two hosts

```bash
# Fat-tree
./htsim_cbr -nodes 54 -tiers 3 -list_paths 1 27

# JSON topology
./htsim_cbr -json_topo abilene.json -list_paths 0 8
```

### List K-shortest paths (by host index)

```bash
./htsim_cbr -json_topo abilene.json -list_kshort 1 9 5
```

### List K-shortest paths (by host name, JSON only)

```bash
./htsim_cbr -json_topo abilene.json -list_kshort_names r2 r10 5
```

### List host name ↔ index mapping (JSON only)

```bash
./htsim_cbr -json_topo abilene.json -list_hosts
```

Output:

```
Host indices (zero-based):
0: r1
1: r2
2: r3
...
```

The indices printed by these commands correspond to the `paths_idx` TM token
and the `-single_path_index` CLI flag.

---

## Queue Logging

Control per-queue logging (useful for measuring queue occupancy / drops):

```bash
# No queue logging (default)
./htsim_cbr -nodes 8 ...

# Simple: log every enqueue/dequeue event
./htsim_cbr -nodes 8 -queue_log simple ...

# Sampling: periodically sample queue depth (default 10 µs)
./htsim_cbr -nodes 8 -queue_log sampling -queue_period_us 50 ...

# Empty: log when queue transitions to/from empty
./htsim_cbr -nodes 8 -queue_log empty -queue_period_us 10 ...
```

---

## Post-Simulation Telemetry

After the simulation completes, three levels of telemetry are printed to
stdout:

### FLOW_STATS (per-flow)

```
FLOW_STATS flow=1 src=0 dst=7 demand_bytes=50000000 admitted_bytes=40000000 sent_bytes=40000000 delivered_bytes=39998500 delivery_ratio=0.999963
```

### PAIR_STATS (per src-dst pair, aggregated)

```
PAIR_STATS src=0 dst=7 demand_bytes=50000000 admitted_bytes=40000000 delivered_bytes=39998500 delivery_ratio=0.999963
```

### GLOBAL_STATS (network-wide)

```
GLOBAL_STATS total_demand_bytes=90000000 total_admitted_bytes=70000000 total_sent_bytes=70000000 total_delivered_bytes=69995000 global_delivery_ratio=0.999929
```

The `delivery_ratio` is `delivered_bytes / admitted_bytes`. This makes it easy
to pipe the output into `grep GLOBAL_STATS` for scripted sweeps.

---

## Worked Examples

### Example 1 — Minimal fat-tree run

```bash
./htsim_cbr -nodes 8 -tiers 2 -rate 500 -end 0.5 -o basic.dat
```

No TM → random permutation traffic. Each flow sends CBR at 500 Mbps for 0.5 s.

### Example 2 — Two multipath flows on Abilene

```bash
./htsim_cbr -json_topo topologies/abilene.json \
            -tm traffic_matrices/abilene_two_flows.tm \
            -rate 100 -end 1.0 -multipath -o abilene_mp.dat
```

TM file (`abilene_two_flows.tm`):

```
Nodes 12
Connections 2
1->9 start 0 paths 2 paths_idx 0,1
0->8 start 0 paths 2 paths_idx 0,1
```

### Example 3 — TE demand/admitted with custom split ratios

```bash
./htsim_cbr -nodes 8 -tiers 2 \
            -tm traffic_matrices/te_demand_admitted_example.tm \
            -end 2.0 -o te_run.dat
```

TM file (see `traffic_matrices/te_demand_admitted_example.tm`):

```
Nodes 8
Connections 3
0->7 id 1 start 0 demand 50000000 admitted 40000000 rate 800 paths 2 split 0.6,0.4
1->6 id 2 start 0 demand 30000000 admitted 20000000
2->5 id 3 start 0 demand 10000000 admitted 10000000 rate 500 paths 2 split 0.5,0.5
```

After the run, grep telemetry:

```bash
./htsim_cbr ... 2>&1 | grep 'GLOBAL_STATS'
```

### Example 4 — Byte-threshold switching

```
Nodes 8
Connections 1
0->7 start 0 admitted 1000000 paths 3 thresholds 200000,600000
```

Sends 1 MB total:
- First 200 KB on path 0
- Next 400 KB on path 1
- Final 400 KB on path 2

```bash
./htsim_cbr -nodes 8 -tiers 2 -tm thresh_example.tm -rate 500 -end 2.0
```

### Example 5 — Explicit Gurobi routes (JSON topology)

```
Nodes 12
Connections 1
1->9 start 0 admitted 5000000 explicit_routes q_r2_r3|q_r3_r10;q_r2_r4|q_r4_r10
```

Two solver-provided paths; split equally by default (or add `split 0.7,0.3`).

```bash
./htsim_cbr -json_topo abilene.json -tm gurobi_routes.tm -rate 200 -end 1.0
```

### Example 6 — Triggers and barriers

```
Nodes 8
Connections 3
Triggers 1

0->7 id 1 start 0 size 1000000 send_done_trigger 10
1->6 id 2 start 0 size 1000000 send_done_trigger 10
2->5 id 3 trigger 10 size 500000

trigger id 10 barrier count 2
```

Flows 1 and 2 start immediately. When **both** finish sending, the barrier
fires trigger 10, which starts flow 3.

### Example 7 — Inspect paths before running

```bash
# See all ECMP paths from host 0 to host 7
./htsim_cbr -nodes 8 -tiers 2 -list_paths 0 7

# See 5-shortest paths in JSON topology
./htsim_cbr -json_topo abilene.json -list_kshort 1 9 5

# Discover host names
./htsim_cbr -json_topo abilene.json -list_hosts
```

### Example 8 — Link failure simulation

```
Nodes 54
Connections 2
Failures 1

0->27 start 0
1->28 start 0

failure switch_type AGG switch_id 0 link_id 1
```

Disables a specific link on an aggregation switch before running.

---

## File Locations

| File | Description |
|------|-------------|
| `sim/datacenter/main_cbr.cpp` | Main driver program |
| `sim/cbr.h` / `sim/cbr.cpp` | CBR source/sink implementation |
| `sim/datacenter/connection_matrix.h` / `.cpp` | Traffic matrix parser |
| `sim/datacenter/json_topology.h` / `.cpp` | JSON graph topology |
| `sim/datacenter/fat_tree_topology.h` / `.cpp` | Fat-tree topology |
| `sim/datacenter/traffic_matrices/` | Example `.tm` files |
