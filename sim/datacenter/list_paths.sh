#!/usr/bin/env bash
set -u

# Configuration
TOPO="./demo/topo/abilene_slow.json"
K_PATHS=5

# Ensure the binary is built
if [[ ! -x ./htsim_cbr ]]; then
    echo "Error: htsim_cbr executable not found in current directory."
    exit 1
fi

echo "Generating path report for topology: $TOPO"
echo "Grouped by Source Node..."

# Outer Loop: The Source
for src in {0..11}; do
    echo ""
    echo "############################################################"
    echo "  SOURCE NODE: $src"
    echo "############################################################"

    # Inner Loop: The Destination 
    for dst in {0..11}; do
        # Skip self-loops
        if [[ "$src" -eq "$dst" ]]; then
            continue
        fi

        echo ""
        echo "   >>> To Destination: Node $dst"

        # 1. Run the tool
        # 2. Grep for lines containing '[' (the paths)
        # 3. Use sed to add 6 spaces of indentation to every line for readability
        ./htsim_cbr -json_topo "$TOPO" -list_kshort "$src" "$dst" "$K_PATHS" \
            | grep "\[" \
            | sed 's/^/      /' 
    done
done