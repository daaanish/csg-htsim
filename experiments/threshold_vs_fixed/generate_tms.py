import os

def generate():
    os.makedirs("experiments/threshold_vs_fixed/tms", exist_ok=True)
    
    # Mapping based on abilene.json "hosts" array order
    # ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12"]
    # r1=0, r2=1, r5=4, r6=5, r7=6, r8=7, r10=9, r11=10
    
    # Test Flow: r1 (0) -> r11 (10)
    src = 0
    dst = 10
    flow_size = 10_000_000 # 10MB
    
    # BG Flow: r5 (4) -> r10 (9)
    # Path: r5->r8->r10 (likely)
    # This conflicts with Test Flow Path A: r1->r2->r5->r8->r10->r11
    bg_src = 4
    bg_dst = 9
    bg_size = 100_000_000 # Long lived
    
    for i in range(1, 6):
        # We cannot set per-flow rate in TM (limitation of codebase).
        # We will control rate via global -rate flag in run_experiment.sh
        
        bg_flow = f"{bg_src}->{bg_dst} start 0 size {bg_size} id {100+i}"
        
        with open(f"experiments/threshold_vs_fixed/tms/fixed_{i}.tm", "w") as f:
            f.write("Nodes 12\n")
            f.write("Connections 2\n")
            f.write(bg_flow + "\n")
            # Main flow: Fixed path 0 (assuming index 0 maps to the congested r5 path)
            # If we are unlucky and 0 maps to the free path, we won't see congestion benefit.
            # But let's assume risk for now, or use experiment to verify.
            f.write(f"{src}->{dst} start 1000 size {flow_size} id 1 paths_idx 0\n")
            
        with open(f"experiments/threshold_vs_fixed/tms/thresh_{i}.tm", "w") as f:
            f.write("Nodes 12\n")
            f.write("Connections 2\n")
            f.write(bg_flow + "\n")
            # Main flow: Threshold switching (paths 2 ensures we select 2 paths, matching 1 threshold)
            f.write(f"{src}->{dst} start 1000 size {flow_size} id 1 paths 2 thresholds 1000000\n")

if __name__ == "__main__":
    generate()
