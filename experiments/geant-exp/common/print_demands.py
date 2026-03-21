import argparse
import sys

# Import the necessary functions from your existing file
try:
    from load_sys_data import load_tm, pair_index_to_src_dst, N_PAIRS
except ImportError:
    print("Error: Could not import load_sys_data. Make sure this script is in the same directory.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Print demands and averages for a given Traffic Matrix (TM).")
    parser.add_argument("--tm", type=int, required=True, help="TM number to load (e.g., 7505)")
    parser.add_argument("--limit", type=int, default=20, 
                        help="Number of pairs to print (default: 20). Set to 462 to see all.")
    parser.add_argument("--nonzero", action="store_true", 
                        help="Only print pairs that have a demand greater than 0")
    args = parser.parse_args()

    print(f"\nLoading Traffic Matrix (TM): {args.tm}")
    
    # Fetch the TM data (returns demands in Gbps as a numpy array)
    try:
        demand_gbps = load_tm(args.tm)
    except FileNotFoundError:
        print(f"Error: Could not find TM file for number {args.tm}. Check your directory paths.")
        sys.exit(1)

    # Calculate statistics
    total_demand_gbps = sum(demand_gbps)
    active_pairs = sum(1 for d in demand_gbps if d > 0)
    
    avg_all_gbps = total_demand_gbps / N_PAIRS
    avg_active_gbps = total_demand_gbps / active_pairs if active_pairs > 0 else 0

    # Print summary statistics
    print("=" * 55)
    print("  TRAFFIC MATRIX STATISTICS")
    print("=" * 55)
    print(f"  Total Demand:        {total_demand_gbps:.4f} Gbps")
    print(f"  Total Pairs:         {N_PAIRS}")
    print(f"  Active ( >0 ) Pairs: {active_pairs}")
    print(f"  Average (All Pairs): {avg_all_gbps:.4f} Gbps  ({avg_all_gbps * 1000:.2f} Mbps)")
    print(f"  Average (Active):    {avg_active_gbps:.4f} Gbps  ({avg_active_gbps * 1000:.2f} Mbps)")
    print("=" * 55)

    # Print a clean table header
    print(f"\n{'Pair':<9} | {'Demand (Gbps)':<15} | {'Demand (Mbps)':<15}")
    print("-" * 45)

    count = 0
    for i in range(N_PAIRS):
        d_gbps = demand_gbps[i]
        
        # Skip zero demands if the flag is passed
        if args.nonzero and d_gbps <= 0:
            continue
            
        src, dst = pair_index_to_src_dst(i)
        d_mbps = d_gbps * 1000.0  # Convert to Mbps to match other scripts
        
        print(f"{src:>2} -> {dst:<2} | {d_gbps:<15.4f} | {d_mbps:<15.2f}")
        
        count += 1
        if count >= args.limit:
            break

    print("-" * 45)
    
    # Footer notes depending on the flags used
    if args.nonzero:
        if count < active_pairs:
            print(f"... and {active_pairs - count} more active pairs hidden. Increase '--limit' to see all.\n")
        else:
            print(f"All {count} active (non-zero) pairs displayed.\n")
    else:
        if count < N_PAIRS:
            print(f"... and {N_PAIRS - count} more pairs hidden. Run with '--limit 462' to see all.\n")
        else:
            print(f"All {N_PAIRS} pairs displayed.\n")

if __name__ == "__main__":
    main()