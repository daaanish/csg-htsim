#!/usr/bin/env python3
"""
Simple script to check the total demand for a given TM in Mbps/Gbps.

Usage:
    python3 scripts/check_demand.py <tm_num>
Example:
    python3 scripts/check_demand.py 7505
"""

import sys
import os

# Ensure we can import from common
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "experiments/geant-exp/common"))

from load_sys_data import load_tm

def main():
    # Hardcoded list of valid TM numbers if no args provided
    DEFAULT_TMS = [7505, 7506, 7507, 7508, 7509]
    
    if len(sys.argv) > 1:
        # Parse command line args
        try:
            tm_nums = [int(arg) for arg in sys.argv[1:]]
        except ValueError as e:
            print(f"Error: TM numbers must be integers. Details: {e}")
            sys.exit(1)
    else:
        # Use default list if none provided
        tm_nums = DEFAULT_TMS
        print(f"No TM numbers provided, using defaults: {DEFAULT_TMS}\n")

    print(f"{'TM Number':>10} | {'Demand (Mbps)':>15} | {'Demand (Gbps)':>15}")
    print("-" * 46)
    
    total_all_mbps = 0.0
    
    for tm_num in tm_nums:
        try:
            demand_gbps = load_tm(tm_num)
            demand_mbps = demand_gbps * 1000.0
            
            total_demand_mbps = float(demand_mbps.sum())
            total_demand_gbps = total_demand_mbps / 1000.0
            
            total_all_mbps += total_demand_mbps
            
            print(f"{tm_num:>10} | {total_demand_mbps:>15,.2f} | {total_demand_gbps:>15,.4f}")
            
        except FileNotFoundError as e:
            print(f"{tm_num:>10} | {'File Not Found':>15} | {'File Not Found':>15}")
        except Exception as e:
            print(f"{tm_num:>10} | {f'Error: {e}':>15} | {f'Error: {e}':>15}")

    print("-" * 46)
    if len(tm_nums) > 1:
        print(f"{'TOTAL':>10} | {total_all_mbps:>15,.2f} | {total_all_mbps / 1000.0:>15,.4f}")

if __name__ == "__main__":
    main()
