import argparse
import sys

try:
    from load_sys_data import load_weights, pair_index_to_src_dst, N_PAIRS
except ImportError:
    print("Error: Could not import load_sys_data. Make sure this script is in the same directory.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Print W1, W2, and T_st for a given sys_data index.")
    parser.add_argument("--idx", type=int, help="sys_data index to load", default=0)
    parser.add_argument("--limit", type=int, default=20, 
                        help="Number of pairs to print (default: 20). Set to 462 to see all.")
    args = parser.parse_args()

    print(f"\nLoading weights and thresholds for sys_data index: {args.idx}")
    
    # Fetch the data using existing function
    w1, w2, t_st = load_weights(args.idx)

    limit = min(args.limit, N_PAIRS)

    # Print a clean table header
    print(f"\n{'Pair':<9} | {'T_st (Mbps)':<12} | {'W1 (Base Path Splits)':<35} | {'W2 (Overflow Path Splits)'}")
    print("-" * 90)

    # Loop through and format the output
    for i in range(limit):
        src, dst = pair_index_to_src_dst(i)
        
        # Format weights to 3 decimal places for clean reading
        w1_str = ", ".join([f"{x:5.3f}" for x in w1[i]])
        w2_str = ", ".join([f"{x:5.3f}" for x in w2[i]])
        t = t_st[i]

        print(f"{src:>2} -> {dst:<2} | {t:<12.2f} | [{w1_str}] | [{w2_str}]")

    # Footer note if output was truncated
    if limit < N_PAIRS:
        print(f"-" * 90)
        print(f"... and {N_PAIRS - limit} more pairs hidden. Run with '--limit 462' to see all.\n")
    else:
        print(f"-" * 90)
        print("All 462 pairs displayed.\n")

if __name__ == "__main__":
    main()