# htsim Project Overview

Once you clone the repo, the main source code of **htsim** is in the `sim` directory:

## sim Directory Contents

### network.h, network.cpp
- Base packet type with a `Route` and attributes  
- Route: list of alternating queues and pipes, with an index for current hop  
- `packet.sendOn` advances the index and calls `receivePacket` on the next hop  
- Supports source routing and ECMP (carries route when ECMP is used)

### eventlist.h, eventlist.cpp
- Event loop for htsim  
- Functions:
    - `sourceIsPending(time_t abs_time)`  
    - `sourceIsPendingRel(time_delta)`  

### queue.h, queue.cpp
- Basic queue implementation  
- Key functions:
    - `receivePacket(packet)`: enqueue or drop if full; starts service if idle  
    - `beginService()`: simulates serialization and schedules callback  
- Supports PAUSE packet transmission via remote endpoint

### pipe.h, pipe.cpp
- Simulates link latency by delaying packets

### compositequeue.h, compositequeue.cpp
- Trimming queue implementation

### queue_lossless_input.h, queue_lossless_input.cpp
- Lossless input buffering with PFC  
- Static thresholds must be configured before creation

### switch.h, switch.cpp
- Abstract switch model: collection of ports (queues)

### tcp.h, tcp.cpp
- TCP NewReno endpoints (unidirectional: `TcpSrc` → `TcpSink`)

### ndp.h, ndp.cpp
- NDP transport implementation

### swift.h, swift.cpp
- Swift congestion control over TCP-like transport

### roce.h, roce.cpp
- Vanilla RoCE (rate-based, go-back-N)

### cbr.h, cbr.cpp
- Constant bitrate sender/sink (no reliability)

All transports send continuously by default (backlogged) or stop after a configured flow size.

---

## Logging Infrastructure

- Most logging is binary for performance  
- Some debug output is text  
- Parse logs with the `parse_output` tool in `sim/`  
- Common loggers:
    - `sinklogger`: samples throughput at receivers  
    - `queuelogger`: periodic queue stats  

---

## Examples and Tests

- Create experiments by writing `main_*` files  
- `sim/tests/` contains example mains (unit-test topologies)  

---

## Datacenter Experiments (`datacenter` subdirectory)

- Topologies: FatTree, DragonFly, BCube, etc.  
- `FatTreeSwitch` with ECMP, PFC support  
- Connection matrix for traffic patterns (incast, random, all-to-all)  
- Prebuilt pattern files and Python generators in `connection_matrices/`  

---

## Main Files for Transports

Configuration via command-line flags:
- Topology size (default: 3-tier FatTree)  
- `-q`: egress queue size  
- `-cwnd`: initial cwnd (for NDP)  
- `--queuetype`: Composite, Random, Lossless_input  
- `--strat`: routing strategy (perm, ecmp_host, ecmp_ar, etc.)  
- `-log`: log level (e.g. `logsink`)  
- `-tm`: connection matrix file  
- `-end`: simulation duration (µs)  
- `-o`: output file

---

## Running Simulations

### Parsing Logs
```bash
sim/parse_output logout.dat -ndp -show
sim/parse_output logout.dat -ascii
```

### ROCE

1. Main file: `main_roce.cpp`
2. Topology: `fat_tree_topology.c(h)` + `FatTreeSwitch`
3. Run example:
     ```bash
     ./htsim_roce \
         -conns 2048 -nodes 8192 \
         -tm connection_matrices/perm_8192n_2048c_2000000.cm \
         -strat ecmp_ar -paths 1 -log sink \
         -end 2000 -mtu 4000 \
         -switch_latency 0.2 -hop_latency 0.8 \
         -start_delta 10 -q 200 \
         -ar_sticky_delta 4 -ar_method pqb \
         -seed 13 &> out
     grep Flow out
     ```

4. Batch scripts:
     ```bash
     ./scripts/run_roce_idle.sh destination_directory
     ./scripts/parse_directory destination_directory
     ```

### NDP / EQDS

- Strategy: `perm`, `ecmp`, `ecmp_host`, `ecmp_ar`  
- Example (source-routing):
    ```bash
    ./htsim_ndp \
        -nodes 16 \
        -tm connection_matrices/perm_16n_16c.cm \
        -cwnd 50 -strat perm \
        -log sink -q 50 -end 1000
    sim/parse_output logout.dat -ndp -show
    ```
- Example (adaptive routing):
    ```bash
    ./htsim_ndp \
        -nodes 16 \
        -tm connection_matrices/perm_16n_16c.cm \
        -cwnd 50 -strat ecmp_ar \
        -ar_method qb -log sink \
        -q 50
    ```