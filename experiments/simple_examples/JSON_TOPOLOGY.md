JSON Topology Support for HTSIM CBR
===================================

This repository now supports loading ad-hoc host/link topologies from a simple JSON file for the CBR driver (`htsim_cbr`). This lets you quickly experiment with arbitrary graphs (not just fat-tree variants) when generating CBR traffic.

CLI Usage
---------

Add the new flag:

```
./htsim_cbr -json_topo /path/to/topology.json -tm /path/to/conn.tm -end 0.5 -rate 100
```

Notes:
* `-json_topo` overrides the fat-tree construction. The flags `-nodes` and `-tiers` become informational only (initially printed) and are replaced by the host count in the JSON.
* Provide a matching traffic matrix with `Nodes <N>` where `<N>` equals the number of hosts in the JSON file.
* All links are treated as bidirectional; a forward and reverse Queue/Pipe pair is built automatically.
* Currently only a SINGLE shortest path is generated between any source/destination pair.

 The `size` token in the TM (e.g. `0->1 start 0 size 15000`) specifies the total number of bytes that connection should send. If omitted or set to 0, the CBR source sends indefinitely (until simulation end or other stop condition).
 Units are bytes.

```
  "hosts": ["h0", "h1", "h2"],
  "links": [
    {"src":"h0", "dst":"h1", "speed_mbps":1000, "latency_us":1},
    {"src":"h1", "dst":"h2", "speed_gbps":10, "latency_us":2},
    {"src":"h0", "dst":"h2", "speed_gbps":10, "latency_us":2}
  ]
}
```

Fields:
* `hosts`: Array of unique host ID strings. Order defines numeric host indices (0..N-1) used in traffic matrices.
* `links`: Array of link objects. Required keys: `src`, `dst`. Provide ONE speed field and ONE latency field.
  * Speed fields (choose one): `speed_mbps`, `speed_gbps` (fallback interpreted as Mbps if ambiguous).
  * Latency fields (choose one): `latency_us`, `latency_ms`, `latency_ns`, `latency_ps`.

Defaults & Implementation Details
---------------------------------
* Each directed edge creates: `Queue(src->dst)` (100 packets buffer) feeding `Pipe(src->dst)` with the given latency.
* Reverse direction is auto-created with identical parameters.
* Queues and pipes are named `q_<src>_<dst>` and `p_<src>_<dst>` and are written to the logfile name map for parsing.
* Queue logging now supported: pass `-queue_log simple|sampling|empty` (and optional `-queue_period_us <us>`) and the JSON topology will attach the chosen logger to every queue.
* Shortest path computation uses BFS; all equal-length shortest paths are enumerated for multipath mode.

Traffic Matrix Example (2 Hosts)
--------------------------------

```
Nodes 2
Connections 1
0->1 start 0 size 0
```

Limitations / Future Extensions
--------------------------------
1. Multiple Path Support: Generate all shortest paths or k-shortest paths for multipath experiments.
2. Per-Link Queue Size: Allow `queue_pkts` field per link. (Currently hard-coded to 100 packets.)
3. Directed / Asymmetric Links: Accept separate speed/latency for reverse direction.
4. Failure Injection: Allow link objects to specify an initial failed state or integrate with existing failure mechanism.
5. Logging & Metrics: Optionally attach sampling loggers to queues via CLI flags.
6. Host-Level Metadata: Support optional host attributes (e.g., position) for visualization.
7. Path Caching: Store computed Routes to avoid regenerating per-flow (currently inexpensive for small graphs).

Troubleshooting
---------------
* Error: "Connection matrix number of nodes is X while I am using Y" → Ensure `Nodes` in TM matches number of JSON hosts.
* No flows created: Your TM may define `Connections 0` or mismatch host count.
* Performance: For large graphs BFS per src/dst could be optimized with a precomputed all-pairs shortest path cache.

Example End-to-End
------------------

```
./htsim_cbr -json_topo ./simple_two_nodes.json -tm ./json_cbr_conn.tm -end 0.02 -rate 50
```

Where `simple_two_nodes.json`:
```
{
  "hosts": ["h0", "h1"],
  "links": [
    {"src": "h0", "dst": "h1", "speed_mbps": 1000, "latency_us": 1}
  ]
}
```
and `json_cbr_conn.tm`:
```
Nodes 2
Connections 1
0->1 start 0 size 0
```

Next Steps Suggestion
---------------------
If you need multipath right away, the simplest incremental change is: after BFS, run a limited DFS constrained by path length equal to the shortest-path distance to enumerate alternative shortest paths, push each as a separate `Route`, and teach the CBR driver to use them when `-multipath` is set with JSON topologies.

Feel free to extend `JsonTopology`—it was intentionally kept self-contained without external JSON dependencies.

Visualization
-------------
You can quickly visualize any JSON topology with NetworkX:

```
python3 visualize_json_topology.py ./simple_square.json --labels -o topo.png
```

Install dependencies (once):
```
pip install -r requirements_networkx.txt
```

Options:
* `--layout` spring|circular|kamada|shell|planar
* `--labels` show node indices and edge (speed, latency)
* `-o` write image instead of interactive window.
