#!/usr/bin/env bash
# List all files needed for the Same-ToR vs Cross-ToR timing experiment

echo "=== TIMING EXPERIMENT FILE INVENTORY ==="
echo ""

echo "📁 REQUIRED FILES (must exist):"
echo ""

# Check core executable
if [ -f "sim/datacenter/htsim_ndp" ]; then
    echo "✅ sim/datacenter/htsim_ndp - HTSIM NDP simulator executable"
else
    echo "❌ sim/datacenter/htsim_ndp - MISSING! Run 'make htsim_ndp' in sim/datacenter"
fi

# Check parse tool
if [ -f "sim/parse_output" ]; then
    echo "✅ sim/parse_output - Results analysis tool"
else
    echo "❌ sim/parse_output - MISSING! Run 'make parse_output' in sim"
fi

echo ""
echo "📄 EXPERIMENT SCRIPTS (provided):"
echo ""

# Check experiment scripts
scripts=(
    "experiments/simple_examples/compare_builtin_timing.sh"
    "experiments/simple_examples/analyze_timing_results.sh"
    "experiments/simple_examples/verify_htsim_routing.sh"
    "experiments/simple_examples/TIMING_EXPERIMENT_README.md"
)

for script in "${scripts[@]}"; do
    if [ -f "$script" ]; then
        echo "✅ $script"
    else
        echo "❌ $script - MISSING!"
    fi
done

echo ""
echo "🔧 GENERATED FILES (created at runtime):"
echo ""

temp_files=(
    "/tmp/same_tor_builtin.tm - Traffic matrix for same-ToR test"
    "/tmp/cross_tor_builtin.tm - Traffic matrix for cross-ToR test"
    "/tmp/same_tor_builtin_results.log - HTSIM results log"
    "/tmp/cross_tor_builtin_results.log - HTSIM results log"
    "/tmp/same_tor_builtin_output.txt - HTSIM console output"
    "/tmp/cross_tor_builtin_output.txt - HTSIM console output"
)

for file in "${temp_files[@]}"; do
    echo "📝 $file"
done

echo ""
echo "🛠️ SYSTEM DEPENDENCIES:"
echo ""

# Check system tools
deps=("bc" "grep" "awk" "head" "tail")
for dep in "${deps[@]}"; do
    if command -v "$dep" >/dev/null 2>&1; then
        echo "✅ $dep - Available"
    else
        echo "❌ $dep - MISSING! Install with your package manager"
    fi
done

echo ""
echo "🏃 QUICK START:"
echo ""
echo "1. Ensure HTSIM is compiled:"
echo "   cd sim/datacenter && make htsim_ndp && cd ../.."
echo ""
echo "2. Run the experiment:"
echo "   ./experiments/simple_examples/compare_builtin_timing.sh"
echo ""
echo "3. Analyze results:"
echo "   ./experiments/simple_examples/analyze_timing_results.sh"
echo ""
echo "4. Read documentation:"
echo "   cat experiments/simple_examples/TIMING_EXPERIMENT_README.md"

echo ""
echo "💾 EXPERIMENT CONFIGURATION:"
echo ""
echo "Flow size: 1GB (1,073,741,824 bytes)"
echo "Network: 8-node, 2-tier fat-tree"
echo "Same-ToR: Host 0 → Host 1"
echo "Cross-ToR: Host 0 → Host 5"
echo "Expected: Cross-ToR significantly slower than Same-ToR"

echo ""
echo "📊 WHAT YOU'LL GET:"
echo ""
echo "• Actual completion times for both flows"
echo "• Performance difference in microseconds/milliseconds"
echo "• Verification that topology affects performance"
echo "• Demonstration of HTSIM's routing accuracy"