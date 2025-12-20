#!/usr/bin/env bash
set -euo pipefail

# Simple CBR/UDP experiment with and without traffic splitting
# Uses sim/datacenter/cbr_test.txt
# Produces logs and parsed ASCII summaries in sim/datacenter/

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIM_DIR="$ROOT_DIR/sim"
DC_DIR="$SIM_DIR/datacenter"
TM_FILE="${TM_FILE:-$DC_DIR/cbr_test.txt}"
PREP_TM="$DC_DIR/cbr_test.prepped.tm"
PREP_TM_PERFLOW="$DC_DIR/cbr_test.perflow.tm"

# Output files
NO_SPLIT_LOG="$DC_DIR/cbr_no_split.log"
SPLIT_LOG="$DC_DIR/cbr_split.log"
NO_SPLIT_TXT="$DC_DIR/cbr_no_split.txt"
SPLIT_TXT="$DC_DIR/cbr_split.txt"
CUSTOM_LOG="$DC_DIR/cbr_split_custom.log"
CUSTOM_TXT="$DC_DIR/cbr_split_custom.txt"
NO_SPLIT_QUEUES_TXT="$DC_DIR/cbr_no_split.queues.txt"
SPLIT_QUEUES_TXT="$DC_DIR/cbr_split.queues.txt"
CUSTOM_QUEUES_TXT="$DC_DIR/cbr_split_custom.queues.txt"
TM_CUSTOM_LOG="$DC_DIR/cbr_split_tm_custom.log"
TM_CUSTOM_TXT="$DC_DIR/cbr_split_tm_custom.txt"
TM_CUSTOM_QUEUES_TXT="$DC_DIR/cbr_split_tm_custom.queues.txt"

# Parameters (override via env: NODES, TIERS, RATE, END, QUEUE, QL_RATE, QL_END, HOST_MBPS, FABRIC_MBPS)
NODES=${NODES:-8}           # must match "Nodes" in cbr_test.txt
TIERS=${TIERS:-2}           # 2 tiers to match small 8-node test and still allow ECMP
RATE=${RATE:-1500}          # Mbps per flow (constant) - stress single 10G-ish link
END=${END:-8}              # seconds
QUEUE=${QUEUE:-15}          # packets per queue
SEED=${SEED:-50}           # RNG seed
# Queue-logging (short runs) parameters; increase QL_RATE/reduce QUEUE/lengthen QL_END to induce drops
# QL_RATE=${QL_RATE:-200}     # Mbps (low rate for queue-verbose runs)
QL_RATE=${RATE}     # Mbps for queue-verbose runs (default: same as RATE)
# Use a smaller queue only for queue-logging runs (defaults to QUEUE if not set)
QL_QUEUE=${QL_QUEUE:-$QUEUE}
QL_END=${QL_END:-5}       # seconds (slightly longer to reduce variance)
# QL_END=${QL_END:-5}       # seconds (slightly longer to reduce variance)

# Extra experiment knobs
SINGLE_PATH_INDEX=${SINGLE_PATH_INDEX:-0}   # which ECMP index to use in no-split runs
PATHS=${PATHS:-2}                           # number of ECMP paths for split runs
SPLIT_RATIOS=${SPLIT_RATIOS:-0.7,0.3}       # custom -split ratios for custom run
# QL_MODE=${QL_MODE:-simple}                  # queue log mode: simple|sampling|empty
QL_MODE=${QL_MODE:-sampling}                  # queue log mode: simple|sampling|empty
QUEUE_TYPE=${QUEUE_TYPE:-}                    # optional: random|composite|lossless|...
QL_PERIOD_US=${QL_PERIOD_US:-10}            # queue log sampling period in microseconds

# Convenience: DROP_DEMO mode forces settings that reliably induce drops
DROP_DEMO=${DROP_DEMO:-0}
DROP_DEMO_SPLIT=${DROP_DEMO_SPLIT:-0}
if [[ "$DROP_DEMO" == "1" ]]; then
  echo "==> DROP_DEMO=1: forcing settings to induce queue drops"
  # Make fabric the bottleneck and shrink buffers, increase rate, run short
  HOST_MBPS=${HOST_MBPS:-1000}
  FABRIC_MBPS=${FABRIC_MBPS:-100}
  QL_MODE=simple           # per-event logging so we can attribute drops per flow
  QL_QUEUE=8               # small buffers to trigger drops faster
  QL_RATE=${QL_RATE:-2000} # high offered load per flow
  QL_END=${QL_END:-2}    # short but long enough to accumulate
  QUEUE_TYPE=${QUEUE_TYPE:-random}   # use drop-tail queues instead of composite
  # Focus on the no-split case and pin flows to the same ECMP index
  RUN_NO_SPLIT=1
  RUN_SPLIT=0
  RUN_CUSTOM=0
  RUN_TM=0
  SINGLE_PATH_INDEX=0
fi

if [[ "$DROP_DEMO_SPLIT" == "1" ]]; then
  echo "==> DROP_DEMO_SPLIT=1: running no-split and split under drop conditions"
  # Same drop-inducing settings, but run both variants side-by-side
  HOST_MBPS=${HOST_MBPS:-1000}
  FABRIC_MBPS=${FABRIC_MBPS:-100}
  QL_MODE=simple
  QL_QUEUE=8
  QL_RATE=${QL_RATE:-2000}
  QL_END=${QL_END:-2}
  QUEUE_TYPE=${QUEUE_TYPE:-random}
  RUN_NO_SPLIT=1
  RUN_SPLIT=1
  RUN_CUSTOM=0
  RUN_TM=0
  SINGLE_PATH_INDEX=${SINGLE_PATH_INDEX:-0}
fi

# Run selection (set to 0 to skip a category)
RUN_NO_SPLIT=${RUN_NO_SPLIT:-1}
RUN_SPLIT=${RUN_SPLIT:-1}
RUN_CUSTOM=${RUN_CUSTOM:-0}
RUN_TM=${RUN_TM:-0}

# Optional: separate host NIC vs fabric link speeds (in Mbps). If set, passed to the driver.
HOST_MBPS=${HOST_MBPS:-10000}
FABRIC_MBPS=${FABRIC_MBPS:-1000}

# Build speed-related CLI args
SPEED_OPTS=()
if [[ -n "${HOST_MBPS}" ]]; then SPEED_OPTS+=( -host_nic_mbps "${HOST_MBPS}" ); fi
if [[ -n "${FABRIC_MBPS}" ]]; then SPEED_OPTS+=( -fabric_mbps "${FABRIC_MBPS}" ); fi

# Build queue-related CLI args
QUEUE_OPTS=()
if [[ -n "${QUEUE_TYPE}" ]]; then QUEUE_OPTS+=( -queue_type "${QUEUE_TYPE}" ); fi

echo "==> Building core sim library (libhtsim.a)"
make -C "$SIM_DIR" -j "$(nproc)" > /dev/null

echo "==> Building htsim_cbr"
make -C "$DC_DIR" htsim_cbr -j "$(nproc)" > /dev/null

if [[ ! -f "$DC_DIR/htsim_cbr" ]]; then
  echo "Error: htsim_cbr binary not found" >&2
  exit 1
fi
if [[ ! -f "$TM_FILE" ]]; then
  echo "Error: traffic matrix not found at $TM_FILE" >&2
  exit 1
fi

# Prepare TM with proper headers (Connections count required by loader)
echo "==> Preparing traffic matrix with headers"
echo "    Using TM: $TM_FILE"
flows_cnt=$(grep -E '^[[:space:]]*[0-9]+->[0-9]+' -c "$TM_FILE" || true)
nodes_line=$(grep -E '^Nodes[[:space:]]+[0-9]+' -m1 "$TM_FILE" || true)
if [[ -z "$nodes_line" ]]; then nodes_line="Nodes $NODES"; fi
{
  echo "$nodes_line"
  echo "Connections $flows_cnt"
  echo "Triggers 0"
  echo "Failures 0"
  # keep only connection lines from the original file
  grep -E '^[[:space:]]*[0-9]+->[0-9]+' "$TM_FILE"
} > "$PREP_TM"

# Create a per-flow TM variant embedding paths/split for the first flow
echo "==> Creating TM with per-flow split (first flow: paths 2 paths_idx 0,1 split 0.7,0.3)"
{
  # Copy headers from prepped TM
  head -n 4 "$PREP_TM"
  # Append attributes to the first connection line only
  awk 'NR>4{if(!done){print $0" paths 2 paths_idx 0,1 split 0.7,0.3"; done=1} else {print $0}}' "$PREP_TM"
} > "$PREP_TM_PERFLOW"

pushd "$DC_DIR" > /dev/null

if [[ "$RUN_NO_SPLIT" == "1" ]]; then
  # Run WITHOUT traffic splitting (single path)
  echo "==> Running CBR (no split)"
  ./htsim_cbr \
    -nodes "$NODES" \
    -tiers "$TIERS" \
    -tm "$PREP_TM" \
    -o "$NO_SPLIT_LOG" \
    -strat single \
    -single_path_index "$SINGLE_PATH_INDEX" \
    -rate "$RATE" \
    -end "$END" \
    -q "$QUEUE" \
    -seed "$SEED" "${SPEED_OPTS[@]}" "${QUEUE_OPTS[@]}" \
    > "$DC_DIR/udp_simple.log" 2>&1
fi

if [[ "$RUN_SPLIT" == "1" ]]; then
  # Run WITH traffic splitting (equal split over PATHS ECMP paths)
  echo "==> Running CBR (with split)"
  ./htsim_cbr \
    -nodes "$NODES" \
    -tiers "$TIERS" \
    -tm "$PREP_TM" \
    -o "$SPLIT_LOG" \
    -strat ecmp \
    -multipath \
    -paths "$PATHS" \
    -rate "$RATE" \
    -end "$END" \
    -q "$QUEUE" \
    -seed "$SEED" "${SPEED_OPTS[@]}" "${QUEUE_OPTS[@]}" \
    > "$DC_DIR/udp_tm_test.log" 2>&1
fi

if [[ "$RUN_CUSTOM" == "1" ]]; then
  # Optional: custom split ratios demo (SPLIT_RATIOS across PATHS ECMP paths)
  echo "==> Running CBR (custom split ${SPLIT_RATIOS})"
  ./htsim_cbr \
    -nodes "$NODES" \
    -tiers "$TIERS" \
    -tm "$PREP_TM" \
    -o "$CUSTOM_LOG" \
    -strat ecmp \
    -multipath \
    -paths "$PATHS" \
    -split "$SPLIT_RATIOS" \
    -rate "$RATE" \
    -end "$END" \
    -q "$QUEUE" \
    -seed "$SEED" "${SPEED_OPTS[@]}" "${QUEUE_OPTS[@]}" \
    > "$DC_DIR/udp_tm_custom.log" 2>&1
fi

echo "==> Queue-count runs (short/low-rate)"
if [[ "$RUN_NO_SPLIT" == "1" ]]; then
  ./htsim_cbr -nodes "$NODES" -tiers "$TIERS" -tm "$PREP_TM" -o "$NO_SPLIT_LOG.ql" -strat single -single_path_index "$SINGLE_PATH_INDEX" -rate "$QL_RATE" -end "$QL_END" -q "$QL_QUEUE" -seed "$SEED" -queue_log "$QL_MODE" -queue_period_us "$QL_PERIOD_US" "${SPEED_OPTS[@]}" "${QUEUE_OPTS[@]}" > /dev/null 2>&1
fi
if [[ "$RUN_SPLIT" == "1" ]]; then
  ./htsim_cbr -nodes "$NODES" -tiers "$TIERS" -tm "$PREP_TM" -o "$SPLIT_LOG.ql"    -strat ecmp -multipath -paths "$PATHS" -rate "$QL_RATE" -end "$QL_END" -q "$QL_QUEUE" -seed "$SEED" -queue_log "$QL_MODE" -queue_period_us "$QL_PERIOD_US" "${SPEED_OPTS[@]}" "${QUEUE_OPTS[@]}" > /dev/null 2>&1
fi
if [[ "$RUN_CUSTOM" == "1" ]]; then
  ./htsim_cbr -nodes "$NODES" -tiers "$TIERS" -tm "$PREP_TM" -o "$CUSTOM_LOG.ql"   -strat ecmp -multipath -paths "$PATHS" -split "$SPLIT_RATIOS" -rate "$QL_RATE" -end "$QL_END" -q "$QL_QUEUE" -seed "$SEED" -queue_log "$QL_MODE" -queue_period_us "$QL_PERIOD_US" "${SPEED_OPTS[@]}" "${QUEUE_OPTS[@]}" > /dev/null 2>&1
fi

if [[ "$RUN_TM" == "1" ]]; then
  # Queue-logging run using TM-embedded per-flow split (no CLI -split)
  ./htsim_cbr -nodes "$NODES" -tiers "$TIERS" -tm "$PREP_TM_PERFLOW" -o "$TM_CUSTOM_LOG.ql" -strat ecmp -multipath -rate "$QL_RATE" -end "$QL_END" -q "$QL_QUEUE" -seed "$SEED" -queue_log "$QL_MODE" -queue_period_us "$QL_PERIOD_US" "${SPEED_OPTS[@]}" "${QUEUE_OPTS[@]}" > /dev/null 2>&1
fi

popd > /dev/null

# Parse logs to ASCII
PARSE_BIN="$SIM_DIR/parse_output"
if [[ ! -x "$PARSE_BIN" ]]; then
  echo "==> Building parse_output"
  make -C "$SIM_DIR" parse_output -j "$(nproc)" > /dev/null || true
fi

if [[ -x "$PARSE_BIN" ]]; then
  echo "==> Parsing logs to ASCII (-cbr)"
  "$PARSE_BIN" "$NO_SPLIT_LOG" -ascii -cbr > "$NO_SPLIT_TXT" || true
  "$PARSE_BIN" "$SPLIT_LOG"    -ascii -cbr > "$SPLIT_TXT"    || true
  "$PARSE_BIN" "$CUSTOM_LOG"   -ascii -cbr > "$CUSTOM_TXT"   || true
  # Also dump verbose queue events for per-link packet counts (from short/low-rate runs)
  "$PARSE_BIN" "$NO_SPLIT_LOG.ql" -ascii -queue-verbose > "$NO_SPLIT_QUEUES_TXT" || true
  "$PARSE_BIN" "$SPLIT_LOG.ql"    -ascii -queue-verbose > "$SPLIT_QUEUES_TXT"    || true
  "$PARSE_BIN" "$CUSTOM_LOG.ql"   -ascii -queue-verbose > "$CUSTOM_QUEUES_TXT"   || true
  "$PARSE_BIN" "$TM_CUSTOM_LOG.ql" -ascii -queue-verbose > "$TM_CUSTOM_QUEUES_TXT" || true
  # Dump ID->Name map (tab-separated) from a main run (includes queues, src/sinks)
  NAMES_FILE="$DC_DIR/id_names.txt"
  "$PARSE_BIN" "$NO_SPLIT_LOG" -names > "$NAMES_FILE" || true
else
  echo "Warning: parse_output not found; skipping ASCII parsing" >&2
fi

echo "==> Done"
echo "Outputs:"
echo "  No split: $NO_SPLIT_LOG  (parsed: $NO_SPLIT_TXT)"
echo "  Split:    $SPLIT_LOG     (parsed: $SPLIT_TXT)"
echo "  Custom:   $CUSTOM_LOG    (parsed: $CUSTOM_TXT)"

# Summaries: per-flow per-queue packet counts (PKT_ENQUEUE)
summarize_queues() {
  local file="$1"
  echo "(file: $(basename "$file"))"
  # Fields present in lines like: "... ID <qid> Ev ENQUEUE Qsize <n> FlowID <fid> PktID <pid>"
  awk -v NAMES_FILE_PATH="$NAMES_FILE" '
    BEGIN{
      FS=" "; OFS=" ";
      # Load ID->Name mapping from NAMES_FILE (tab-separated)
      while ((getline line < NAMES_FILE_PATH) > 0) {
        split(line, a, "\t");
        if (length(a) >= 2) {
          id=a[1]; name=line; sub(/^\S+\t/, "", name); idname[id]=name;
        }
      }
      close(NAMES_FILE_PATH);
    }
    $0 ~ / Ev ENQUEUE / {
      for (i=1;i<=NF;i++) {
        if ($i=="ID") {qid=$(i+1)}
        if ($i=="FlowID") {fid=$(i+1)}
      }
      if (qid!="" && fid!="") cnt[fid"/"qid]++
    }
    END{
      # Print per-flow queue counts
      for (k in cnt) {
        split(k,a,"/"); fid=a[1]; qid=a[2];
        qn = ((qid in idname) ? idname[qid] : "?");
        printf("Flow %s Queue %s (%s) Enqueued %d\n", fid, qid, qn, cnt[k]);
      }
    }
  ' "$file" | sort -V
}

# Summaries: per-flow per-queue drop counts and drop rates
summarize_drops() {
  local file="$1"
  echo "(file: $(basename "$file"))"
  awk -v NAMES_FILE_PATH="$NAMES_FILE" '
    BEGIN{
      FS=" "; OFS=" ";
      while ((getline line < NAMES_FILE_PATH) > 0) {
        split(line, a, "\t");
        if (length(a) >= 2) { id=a[1]; name=line; sub(/^\S+\t/, "", name); idname[id]=name; }
      }
      close(NAMES_FILE_PATH);
    }
    $0 ~ / Ev (ENQUEUE|DROP) / {
      for (i=1;i<=NF;i++) {
        if ($i=="ID") {qid=$(i+1)}
        if ($i=="FlowID") {fid=$(i+1)}
        if ($i=="Ev") {ev=$(i+1)}
      }
      if (qid!="" && fid!="") {
        key=fid"/"qid
        if (ev=="ENQUEUE") enq[key]++
        else if (ev=="DROP") drop[key]++
      }
    }
    END{
      # Print per-flow per-queue: Enq, Drop, DropRate
      for (k in enq) {
        split(k,a,"/"); fid=a[1]; qid=a[2]; d=(k in drop)?drop[k]:0; e=enq[k];
        rate=(e+d>0)?(d*100.0/(e+d)):0.0; qn=((qid in idname)?idname[qid]:"?");
        printf("Flow %s Queue %s (%s) Enq %d Drop %d DropRate %.2f%%\n", fid, qid, qn, e, d, rate);
      }
    }
  ' "$file" | sort -V
}

# Aggregate drops per flow across all queues
summarize_drops_aggregate() {
  local file="$1"
  echo "(file: $(basename "$file"))"
  awk '
    $0 ~ / Ev (ENQUEUE|DROP) / {
      for (i=1;i<=NF;i++) {
        if ($i=="FlowID") {fid=$(i+1)}
        if ($i=="Ev") {ev=$(i+1)}
      }
      if (fid!="") {
        if (ev=="ENQUEUE") enq[fid]++
        else if (ev=="DROP") drop[fid]++
      }
    }
    END{
      for (f in enq) {
        e=enq[f]; d=((f in drop)?drop[f]:0); rate=(e+d>0)?(d*100.0/(e+d)):0.0;
        printf("Flow %s Enq %d Drop %d DropRate %.2f%%\n", f, e, d, rate);
      }
    }
  ' "$file" | sort -V
}

if [[ -f "$NO_SPLIT_QUEUES_TXT" ]]; then
  echo "\n-- Queue usage (no split) --"
  summarize_queues "$NO_SPLIT_QUEUES_TXT" | head -n 40
fi

if [[ -f "$SPLIT_QUEUES_TXT" ]]; then
  echo "\n-- Queue usage (equal split) --"
  summarize_queues "$SPLIT_QUEUES_TXT" | head -n 40
fi

if [[ -f "$CUSTOM_QUEUES_TXT" ]]; then
  echo "\n-- Queue usage (custom split) --"
  summarize_queues "$CUSTOM_QUEUES_TXT" | head -n 40
fi

if [[ -f "$TM_CUSTOM_QUEUES_TXT" ]]; then
  echo "\n-- Queue usage (TM-embedded split for flow 1) --"
  summarize_queues "$TM_CUSTOM_QUEUES_TXT" | head -n 40
fi

if [[ -f "$CUSTOM_QUEUES_TXT" ]]; then
  echo "\n-- Drops (custom split) --"
  summarize_drops "$CUSTOM_QUEUES_TXT" | head -n 40
  echo "\n-- Drops AGG (custom split) --"
  summarize_drops_aggregate "$CUSTOM_QUEUES_TXT" | head -n 40
fi

if [[ -f "$TM_CUSTOM_QUEUES_TXT" ]]; then
  echo "\n-- Drops (TM-embedded split) --"
  summarize_drops "$TM_CUSTOM_QUEUES_TXT" | head -n 40
  echo "\n-- Drops AGG (TM-embedded split) --"
  summarize_drops_aggregate "$TM_CUSTOM_QUEUES_TXT" | head -n 40
fi

# Quick one-line summaries of average sink rate (bytes/sec)
if [[ -f "$NO_SPLIT_TXT" && -s "$NO_SPLIT_TXT" ]]; then
  echo "\n-- No split (avg sink rates) --"
  awk 'match($0,/ID ([0-9]+)/,a) && match($0,/Rate ([0-9]+)/,b){id=a[1]; rate=b[1]; sum[id]+=rate; cnt[id]++} END{for (id in sum) printf "ID %s avg_rate %.0f Bps\n", id, sum[id]/cnt[id]}' "$NO_SPLIT_TXT" | sort -V
fi
if [[ -f "$SPLIT_TXT" && -s "$SPLIT_TXT" ]]; then
  echo "\n-- With split (avg sink rates) --"
  awk 'match($0,/ID ([0-9]+)/,a) && match($0,/Rate ([0-9]+)/,b){id=a[1]; rate=b[1]; sum[id]+=rate; cnt[id]++} END{for (id in sum) printf "ID %s avg_rate %.0f Bps\n", id, sum[id]/cnt[id]}' "$SPLIT_TXT" | sort -V
fi

if [[ -f "$TM_CUSTOM_TXT" && -s "$TM_CUSTOM_TXT" ]]; then
  echo "\n-- TM-embedded split (avg sink rates) --"
  awk 'match($0,/ID ([0-9]+)/,a) && match($0,/Rate ([0-9]+)/,b){id=a[1]; rate=b[1]; sum[id]+=rate; cnt[id]++} END{for (id in sum) printf "ID %s avg_rate %.0f Bps\n", id, sum[id]/cnt[id]}' "$TM_CUSTOM_TXT" | sort -V
fi

if [[ -f "$NO_SPLIT_QUEUES_TXT" ]]; then
  echo "\n-- Drops (no split) --"
  summarize_drops "$NO_SPLIT_QUEUES_TXT" | head -n 40
  echo "\n-- Drops AGG (no split) --"
  summarize_drops_aggregate "$NO_SPLIT_QUEUES_TXT" | head -n 40
fi

if [[ -f "$SPLIT_QUEUES_TXT" ]]; then
  echo "\n-- Drops (equal split) --"
  summarize_drops "$SPLIT_QUEUES_TXT" | head -n 40
  echo "\n-- Drops AGG (equal split) --"
  summarize_drops_aggregate "$SPLIT_QUEUES_TXT" | head -n 40
fi

# Side-by-side comparisons when DROP_DEMO_SPLIT is enabled and both outputs exist
if [[ "$DROP_DEMO_SPLIT" == "1" && -f "$NO_SPLIT_QUEUES_TXT" && -f "$SPLIT_QUEUES_TXT" ]]; then
  echo "\n== Side-by-side: Drops per flow (no split vs split) =="
  awk '
    FNR==1 { fileIdx++ }
    $0 ~ / Ev (ENQUEUE|DROP) / {
      for (i=1;i<=NF;i++) {
        if ($i=="FlowID") fid=$(i+1)
        if ($i=="Ev") ev=$(i+1)
      }
      if (fid!="") {
        if (fileIdx==1) {
          if (ev=="ENQUEUE") enq1[fid]++
          else if (ev=="DROP") drop1[fid]++
        } else {
          if (ev=="ENQUEUE") enq2[fid]++
          else if (ev=="DROP") drop2[fid]++
        }
      }
    }
    END{
      total_e1=total_d1=total_e2=total_d2=0
      for (f in enq1) {
        e1=enq1[f]; d1=(f in drop1)?drop1[f]:0; r1=(e1+d1>0)?(d1*100.0/(e1+d1)):0.0;
        e2=(f in enq2)?enq2[f]:0; d2=(f in drop2)?drop2[f]:0; r2=(e2+d2>0)?(d2*100.0/(e2+d2)):0.0;
        printf("Flow %s | no-split: Enq %d Drop %d (%.2f%%) | split: Enq %d Drop %d (%.2f%%)\n", f, e1, d1, r1, e2, d2, r2);
        total_e1+=e1; total_d1+=d1; total_e2+=e2; total_d2+=d2;
      }
      # include flows that only appear in split
      for (f in enq2) if (!(f in enq1)) {
        e1=0; d1=(f in drop1)?drop1[f]:0; r1=(e1+d1>0)?(d1*100.0/(e1+d1)):0.0;
        e2=enq2[f]; d2=(f in drop2)?drop2[f]:0; r2=(e2+d2>0)?(d2*100.0/(e2+d2)):0.0;
        printf("Flow %s | no-split: Enq %d Drop %d (%.2f%%) | split: Enq %d Drop %d (%.2f%%)\n", f, e1, d1, r1, e2, d2, r2);
        total_e1+=e1; total_d1+=d1; total_e2+=e2; total_d2+=d2;
      }
      tr1=(total_e1+total_d1>0)?(total_d1*100.0/(total_e1+total_d1)):0.0;
      tr2=(total_e2+total_d2>0)?(total_d2*100.0/(total_e2+total_d2)):0.0;
      printf("TOTAL | no-split: Enq %d Drop %d (%.2f%%) | split: Enq %d Drop %d (%.2f%%)\n", total_e1, total_d1, tr1, total_e2, total_d2, tr2);
    }
  ' "$NO_SPLIT_QUEUES_TXT" "$SPLIT_QUEUES_TXT" | sort -V

  if [[ -f "$NO_SPLIT_TXT" && -f "$SPLIT_TXT" ]]; then
    echo "\n== Side-by-side: Avg sink rates (no split vs split) =="
    awk '
      FNR==1 { fileIdx++ }
      {
        if (match($0,/ID ([0-9]+)/,a) && match($0,/Rate ([0-9]+)/,b)) {
          id=a[1]; rate=b[1];
          if (fileIdx==1) { sum1[id]+=rate; cnt1[id]++ } else { sum2[id]+=rate; cnt2[id]++ }
        }
      }
      END{
        for (id in sum1) {
          avg1=sum1[id]/cnt1[id]; avg2=(id in sum2)?(sum2[id]/cnt2[id]):0;
          printf("Sink %s | no-split avg %.0f Bps | split avg %.0f Bps\n", id, avg1, avg2);
        }
        for (id in sum2) if (!(id in sum1)) {
          avg1=0; avg2=sum2[id]/cnt2[id];
          printf("Sink %s | no-split avg %.0f Bps | split avg %.0f Bps\n", id, avg1, avg2);
        }
      }
    ' "$NO_SPLIT_TXT" "$SPLIT_TXT" | sort -V
  fi
fi