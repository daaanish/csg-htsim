### quick copy/paste 

Run from `sim/datacenter` unless noted.

- Build, single-path baseline and parse sink rates:
```bash
make -j$(nproc) && make -C . htsim_cbr -j$(nproc)
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat single -single_path_index 0 -rate 1000 -end 5 -q 15 \
  -o /tmp/cbr_single.log
../parse_output /tmp/cbr_single.log -cbr | head
```

- ECMP equal split and parse:
```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat ecmp -multipath -paths 2 -rate 1000 -end 5 -q 15 \
  -o /tmp/cbr_ecmp2.log
../parse_output /tmp/cbr_ecmp2.log -cbr | head
```

- Quick drop demo (no-split):
```bash
DROP_DEMO=1 ../../experiments/simple_examples/run_cbr_split_test.sh
```

- Side-by-side drop demo (no-split vs split):
```bash
DROP_DEMO_SPLIT=1 ../../experiments/simple_examples/run_cbr_split_test.sh
```

- Per-flow drop summary (simple mode logfile -> CSV):
```bash
# produce ASCII and export flow/queue drop stats as CSV
../parse_output /tmp/cbr_simple.ql -ascii | \
  awk 'BEGIN{FS=" ";OFS=",";print "flow_id,queue_id,enq,drop,drop_rate"} \
       / Ev (ENQUEUE|DROP) / {fid=qid=ev=""; \
         for(i=1;i<=NF;i++){if($i=="ID")qid=$(i+1); if($i=="FlowID")fid=$(i+1); if($i=="Ev")ev=$(i+1)} \
         if(fid&&qid){k=fid"/"qid; if(ev=="ENQUEUE")E[k]++; else if(ev=="DROP")D[k]++}} \
       END{for(k in E){split(k,a,"/"); e=E[k]; d=(k in D)?D[k]:0; r=(e+d>0)?(d*100.0/(e+d)):0; \
           print a[1],a[2],e,d,r}}' > /tmp/cbr_drops.csv && column -t -s, /tmp/cbr_drops.csv | head
```

- Sampling mode: show any intervals with drops:
```bash
../parse_output /tmp/cbr_sampling.ql -ascii | grep "LastDropped [1-9]"
```

Binary location: `sim/datacenter/htsim_cbr`

Traffic Matrix: `sim/datacenter/cbr_test.txt` (can provide my own with `-tm`)

---

## CLI reference

- Topology and traffic
  - `-nodes N` number of end hosts (must match TM `Nodes`)
  - `-tiers T` 2 or 3 (fat-tree tiers)
  - `-tm FILE` traffic matrix file
  - `-strat single|rand|perm|ecmp` route strategy
  - `-multipath` enable multi-path (used with `-strat ecmp`)
  - `-paths K` number of ECMP paths to use (when multipath)
  - `-split r1,r2,...` split ratios across chosen paths (auto-normalized)
  - `-single_path_index I` pin single-path selection to ECMP index I
  - `-list_paths SRC DST` print indexed ECMP routes for SRC→DST and exit

- Rates, duration, buffers, randomness
  - `-rate Mbps` per-flow CBR rate
  - `-end seconds` simulation end time (seconds)
  - `-q packets` per-queue buffer (packets)
  - `-seed N` RNG seed (affects random route selection if used)

- Link speeds and latencies
  - `-host_nic_mbps Mbps` host↔ToR link speed
  - `-fabric_mbps Mbps` fabric (ToR↔Agg↔Core) linkspeed (alias: `-linkspeed`)
  - `-hop_latency us`, `-switch_latency us` per-hop / switching latency

- Queue types and logging
  - `-queue_type random|composite|ecn|composite_ecn|lossless|lossless_input|lossless_input_ecn|ecn_prio|priority`
  - `-queue_log simple|sampling|empty` queue logging mode
    - simple: per-event (ENQUEUE, DEQUEUE, DROP) with FlowID attribution
    - sampling/empty: periodic snapshots (min/max/last); use `-queue_period_us`
  - `-queue_period_us us` sampling period for queue logging

- Output file
  - `-o logfile` output log (binary htsim format)

---

## 1) Single-path vs ECMP (equal split)

- Single path (pin to one ECMP index):
```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat single -single_path_index 0 \
  -rate 1000 -end 5 -q 15 -o /tmp/cbr_single.log
```

- ECMP equal split across 2 paths:
```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat ecmp -multipath -paths 2 \
  -rate 1000 -end 5 -q 15 -o /tmp/cbr_ecmp2.log
```

- Parse average sink rates (bytes/sec):
```bash
../parse_output /tmp/cbr_single.log -cbr | head
../parse_output /tmp/cbr_ecmp2.log -cbr | head
```

## 2) Custom split ratios (per-run)

- 70/30 split across 2 ECMP paths:
```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat ecmp -multipath -paths 2 -split 0.7,0.3 \
  -rate 1000 -end 5 -q 15 -o /tmp/cbr_ecmp_custom.log
```

- Compare sink rates:
```bash
../parse_output /tmp/cbr_ecmp_custom.log -cbr | head
```

## 3) Explicit per-flow ECMP indices via TM (paths_idx)

- First, list ECMP path indices for a pair (e.g., host 0 → 3):
```bash
./htsim_cbr -nodes 8 -tiers 2 -list_paths 0 3 -o /dev/null
```

- Tiny TM that pins a flow to specific paths with a split (0→3 on paths 0 and 1 with 70/30):
```bash
cat > /tmp/perflow.tm << 'EOF'
Nodes 8
Connections 1
Triggers 0
Failures 0
0->3 paths 2 paths_idx 0,1 split 0.7,0.3
EOF

./htsim_cbr -nodes 8 -tiers 2 -tm /tmp/perflow.tm \
  -strat ecmp -multipath -rate 1000 -end 5 -q 15 -o /tmp/cbr_tm_custom.log
../parse_output /tmp/cbr_tm_custom.log -cbr -show
```

Notes:
- TM keywords supported per connection: `paths K`, `paths_idx i,j,...`, `split r1,r2,...`.
- When both CLI and TM provide settings, TM takes precedence for that flow.

## 4) Queue logging (sampling) for link usage and drops by queue

- Run with queue sampling:
```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat ecmp -multipath -paths 2 \
  -rate 1500 -end 0.5 -q 15 \
  -queue_log sampling -queue_period_us 50 \
  -o /tmp/cbr_sampling.ql
```

- Parse queue snapshots (min/max/last, drops):
```bash
../parse_output /tmp/cbr_sampling.ql -ascii | grep "Type QUEUE_APPROX" | head
# Show any interval with drops:
../parse_output /tmp/cbr_sampling.ql -ascii | grep "LastDropped [1-9]"
```

What to look for:
- RANGE lines: `LastQ/MinQ/MaxQ` for the window
- OVERLOW lines: `LastIdled` (idle capacity), `LastDropped` (bytes), `QueueBuf` (bytes)

## 5) Queue logging (simple) for per-flow drop attribution

Per-event queue logging lets you attribute drops to individual flows. Using drop-tail queues for visible drops:

```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat single -single_path_index 0 \
  -rate 2000 -end 0.3 -q 8 \
  -queue_type random \
  -queue_log simple \
  -o /tmp/cbr_simple.ql
```

- Per-flow drops:
```bash
../parse_output /tmp/cbr_simple.ql -ascii | \
  awk '/ Type QUEUE / && / Ev DROP / {for(i=1;i<=NF;i++){if($i=="FlowID"){print $(i+1)}}}' | \
  sort | uniq -c | awk '{printf("flow=%s drops=%s\n",$2,$1)}'
```

- Per-flow per-queue drop/arrival counts (with drop rate):
```bash
../parse_output /tmp/cbr_simple.ql -ascii | \
  awk '/ Ev (ENQUEUE|DROP) / {qid=fid=ev=""; for(i=1;i<=NF;i++){if($i=="ID")qid=$(i+1); if($i=="FlowID")fid=$(i+1); if($i=="Ev")ev=$(i+1)}; if(qid&&fid){key=fid"/"qid; if(ev=="ENQUEUE")enq[key]++; else if(ev=="DROP")drop[key]++}} END{for(k in enq){split(k,a,"/"); fid=a[1]; qid=a[2]; d=(k in drop)?drop[k]:0; e=enq[k]; rate=(e+d>0)?(d*100.0/(e+d)):0; printf("Flow %s Queue %s Enq %d Drop %d DropRate %.2f%%\n", fid, qid, e, d, rate)}}' | \
  sort -V
```

- Map queue IDs to names for readability:
```bash
../parse_output /tmp/cbr_simple.ql -names | head
```

## 6) Create bottlenecks to induce drops

- Fabric bottleneck (slow fabric, fast NICs):
```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat single -single_path_index 0 \
  -rate 2000 -end 0.3 -q 8 \
  -host_nic_mbps 1000 -fabric_mbps 100 \
  -queue_type random \
  -queue_log sampling -queue_period_us 50 \
  -o /tmp/cbr_fabric_bottleneck.ql
../parse_output /tmp/cbr_fabric_bottleneck.ql -ascii | grep "LastDropped [1-9]"
```

- Incast (host downlink bottleneck):
```bash
./htsim_cbr -nodes 8 -tiers 2 -tm ./cbr_test.txt \
  -strat single -single_path_index 0 \
  -rate 800 -end 0.3 -q 8 \
  -host_nic_mbps 100 -fabric_mbps 1000 \
  -queue_type random \
  -queue_log sampling -queue_period_us 50 \
  -o /tmp/cbr_incast.ql
```

Note: Composite queues don’t “drop”; they strip/mark. Use `-queue_type random` for drop-tail behavior when demonstrating drops.

## 7) Useful parsing patterns

- Average sink rate summary:
```bash
../parse_output /tmp/cbr_single.log -cbr
```

- Full ASCII dump (then filter):
```bash
../parse_output /tmp/cbr_sampling.ql -ascii | head
```

- Queue events (simple mode only):
```bash
../parse_output /tmp/cbr_simple.ql -ascii | grep "Type QUEUE " | head
```

- Find which queues ever dropped (sampling mode):
```bash
../parse_output /tmp/cbr_sampling.ql -ascii | \
  awk '/Ev OVERLOW/ {for(i=1;i<=NF;i++){if($i=="LastDropped"){ld=$(i+1)} if($i=="Name"){print_ld=1; name=$0}} if(ld+0>0&&print_ld){print $0; print_ld=0; ld=0}}'
```

## 8) Side-by-side comparisons (scripted)

Use the helper script to run reproducible comparisons and summaries:

- Run both no-split and equal-split under drop conditions and print side-by-side drop and sink summaries:
```bash
cd sim/datacenter
DROP_DEMO_SPLIT=1 ../../experiments/simple_examples/run_cbr_split_test.sh
```

Outputs include:
- “Side-by-side: Drops per flow (no split vs split)” with totals
- “Side-by-side: Avg sink rates (no split vs split)”

For a quick single run drop demo (no-split only):
```bash
cd sim/datacenter
DROP_DEMO=1 ../../experiments/simple_examples/run_cbr_split_test.sh
```

## 9) Other things

- Change ECMP selection for single-path runs: `-single_path_index i`
- Change number of ECMP paths: `-paths K`
- Custom per-run split: `-split r1,r2,...`
- Custom per-flow split/indices in TM: `paths K paths_idx i,j,... split r1,r2,...`
- Identify ECMP indices for a pair: `-list_paths SRC DST -o /dev/null`
- Reduce buffer to see drops faster: lower `-q` (e.g., 8 or 5 pkts)
- Extend duration for more stable averages: increase `-end`
- Prefer `-queue_type random` for clear drop demonstrations