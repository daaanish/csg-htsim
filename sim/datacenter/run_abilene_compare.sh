#!/usr/bin/env bash
set -euo pipefail

# Run Abilene single-path vs split-path TMs and compare throughput.
# Usage: ./run_abilene_compare.sh [--fabric <Mbps>] [--end <seconds>]

FABRIC_ARG=()
END_ARG=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fabric)
      shift
      [[ $# -gt 0 ]] || { echo "--fabric requires a value"; exit 1; }
      FABRIC_ARG=("-fabric_mbps" "$1")
      shift
      ;;
    --end)
      shift
      [[ $# -gt 0 ]] || { echo "--end requires a value"; exit 1; }
      END_ARG=("-end" "$1")
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2; exit 1;;
  esac
done

cd "$(dirname "$0")"

# Ensure binaries exist
if [[ ! -x ./htsim_cbr ]]; then
  echo "Building htsim_cbr..."
  make htsim_cbr
fi
if [[ ! -x ../parse_output ]]; then
  echo "Building parse_output..."
  (cd .. && make parse_output)
fi

TOPO=./demo/topo/abilene_slow.json
TM_SINGLE=./demo/tms/abilene_tms/abilene_e3.tm
TM_SPLIT=./demo/tms/abilene_tms/abilene_e4.tm

OUT_SINGLE=logout_single.dat
OUT_SPLIT=logout_split.dat

echo "== Running single-path case (no split) =="
set -x
./htsim_cbr -json_topo "$TOPO" -tm "$TM_SINGLE" -o "$OUT_SINGLE" ${FABRIC_ARG[@]} ${END_ARG[@]}
set +x

echo
echo "== Running split case (paths 0,1 at 50/50) =="
set -x
./htsim_cbr -json_topo "$TOPO" -tm "$TM_SPLIT" -o "$OUT_SPLIT" ${FABRIC_ARG[@]} ${END_ARG[@]}
set +x

echo
echo "== Throughput per flow (Mbps) =="
echo "-- Single path --"
../parse_output "$OUT_SINGLE" -cbr -show || true
echo
echo "-- Split (0.5/0.5) --"
../parse_output "$OUT_SPLIT" -cbr -show || true

echo
echo "== Summary (means) =="
echo -n "Single: "; ../parse_output "$OUT_SINGLE" -cbr | tail -n1 || true
echo -n "Split : "; ../parse_output "$OUT_SPLIT"  -cbr | tail -n1 || true

echo
echo "Done. Logs: $OUT_SINGLE, $OUT_SPLIT"
