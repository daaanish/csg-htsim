
import os
import glob
import subprocess

def get_throughput(logfile):
    # Use parse_output tool from the simulator
    # Command: parse_output <logfile> -cbr
    # Output format:
    # Service Rate:   Min: ... Mean: ... Max: ...
    # Throughput:     Min: ... Mean: ... Max: ...
    # We want to grab the Mean Throughput line
    
    cmd = ["sim/parse_output", logfile, "-cbr"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if "total mean" in line:
                # Example: Mean of lower 10pc (1 entries) is 49.35 Mbps total mean 49.90 Mbps mean2 ...
                try:
                    # simplistic parsing: find "total mean " and take next word
                    parts = line.split("total mean ")
                    if len(parts) > 1:
                        val_str = parts[1].split()[0]
                        val = float(val_str)
                        return val
                except:
                    pass
    except Exception as e:
        print(f"Error parsing {logfile}: {e}")
        return 0.0
    return 0.0

def main():
    log_dir = "experiments/threshold_vs_fixed/logs"
    print(f"{'Run':<5} | {'Fixed (Mbps)':<15} | {'Threshold (Mbps)':<15} | {'Gain':<10}")
    print("-" * 55)
    
    fixed_measurements = []
    thresh_measurements = []
    
    for i in range(1, 6):
        fixed_log = f"{log_dir}/fixed_{i}.log"
        thresh_log = f"{log_dir}/thresh_{i}.log"
        
        t_fixed = get_throughput(fixed_log)
        t_thresh = get_throughput(thresh_log)
        
        fixed_measurements.append(t_fixed)
        thresh_measurements.append(t_thresh)
        
        gain = 0.0
        if t_fixed > 0:
            gain = (t_thresh - t_fixed) / t_fixed * 100
            
        print(f"{i:<5} | {t_fixed:<15.2f} | {t_thresh:<15.2f} | {gain:+.2f}%")
        
    avg_fixed = sum(fixed_measurements) / len(fixed_measurements)
    avg_thresh = sum(thresh_measurements) / len(thresh_measurements)
    avg_gain = 0.0
    if avg_fixed > 0:
        avg_gain = (avg_thresh - avg_fixed) / avg_fixed * 100
        
    print("-" * 55)
    print(f"{'Avg':<5} | {avg_fixed:<15.2f} | {avg_thresh:<15.2f} | {avg_gain:+.2f}%")

if __name__ == "__main__":
    main()
