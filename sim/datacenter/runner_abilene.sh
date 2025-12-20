#!/usr/bin/env bash
set -euo pipefail

# Run Abilene exp with files of choice
# At various times, different split ratios for different flows are to be used

TOPO=./demo/topo/abilene_slow.json
TM_FIRST=./demo/tms/abilene_tms/abilene_t1.tm
TM_SECOND=./demo/tms/abilene_tms/abilene_t2.tm

OUT_FIRST=logout_first.dat
OUT_SECOND=logout_second.dat

echo "== Using first time instance splits =="
set -x
./htsim_cbr -json_topo "$TOPO" -tm "$TM_FIRST" -o "$OUT_FIRST"
set +x

echo
echo "== Using second time instance splits =="
set -x
./htsim_cbr -json_topo "$TOPO" -tm "$TM_SECOND" -o "$OUT_SECOND"
set +x

echo
echo "== Throughput per flow (Mbps) =="
echo "For first time instance, per flow:"
../parse_output "$OUT_FIRST" -cbr -show || true
echo
echo "For second time instance, per flow:"
../parse_output "$OUT_SECOND" -cbr -show || true
echo
echo "== Summary (means) =="
echo -n "First: "; ../parse_output "$OUT_FIRST" -cbr | tail -n1 || true
echo -n "Second: "; ../parse_output "$OUT_SECOND"  -cbr | tail -n1 || true
echo
echo "Done. Logs: $OUT_FIRST, $OUT_SECOND"
