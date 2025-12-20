# Example: Custom Routes with Split Ratios

This document shows a complete working example of using custom paths and split ratios in HTSIM CBR.

## Example Output

When running the example, you'll see output like this:

```
Flow 1: 0 -> 27 @ 50 Mbps with 2 paths, ratios: 0.7, 0.3
Flow 2: 1 -> 28 @ 50 Mbps with 2 paths, ratios: 0.5, 0.5
Flow 3: 2 -> 29 @ 50 Mbps with 3 paths, ratios: 0.5, 0.3, 0.2
```

This shows:
- **Flow 1**: Uses 2 paths with 70% on path 0, 30% on path 1
- **Flow 2**: Uses 2 paths with 50% on each path (equal split)
- **Flow 3**: Uses 3 paths with 50% on path 0, 30% on path 1, 20% on path 2

## How to Run

### Step 1: Create a traffic matrix file

```bash
cat > test_custom_split_ratios.tm << EOF
Nodes 54
Connections 3
0->27 start 1000000
1->28 start 1000000
2->29 start 1000000
EOF
```

### Step 2: Run the simulation

```bash
cd sim/datacenter
./htsim_cbr -nodes 54 -tiers 3 -tm test_custom_split_ratios.tm -rate 50 -end 0.1 -o split_ratios_example.log
```

### Step 3: Check the output

The simulation will output:
- Console output showing flows with their split ratios
- Log file with detailed simulation data

## Code Example

The implementation in `main_cbr.cpp` (lines 311-353) shows:

```cpp
// EXAMPLE: Use multi-path with custom split ratios for different flows
if (net_paths[src][dest]->size() >= 2) {
    vector<const Route*> selected_paths;
    vector<double> split_ratios;
    
    // Different split ratios for different flows
    if (flow_id == 1) {
        // Flow 1: 70% on path 0, 30% on path 1
        selected_paths.push_back(net_paths[src][dest]->at(0));
        selected_paths.push_back(net_paths[src][dest]->at(1));
        split_ratios.push_back(0.7);
        split_ratios.push_back(0.3);
    } else if (flow_id == 2) {
        // Flow 2: 50% on path 0, 50% on path 1 (equal split)
        selected_paths.push_back(net_paths[src][dest]->at(0));
        selected_paths.push_back(net_paths[src][dest]->at(1));
        split_ratios.push_back(0.5);
        split_ratios.push_back(0.5);
    } else if (flow_id == 3 && net_paths[src][dest]->size() >= 3) {
        // Flow 3: 3 paths with 50%, 30%, 20% split
        selected_paths.push_back(net_paths[src][dest]->at(0));
        selected_paths.push_back(net_paths[src][dest]->at(1));
        selected_paths.push_back(net_paths[src][dest]->at(2));
        split_ratios.push_back(0.5);
        split_ratios.push_back(0.3);
        split_ratios.push_back(0.2);
    } else {
        // Default: 2 paths with 60/40 split
        selected_paths.push_back(net_paths[src][dest]->at(0));
        selected_paths.push_back(net_paths[src][dest]->at(1));
        split_ratios.push_back(0.6);
        split_ratios.push_back(0.4);
    }
    
    // Create flow with multi-path and split ratios
    create_cbr_flow_multipath(src, dest, top, eventlist, logfile, 
                              cbr_rate, cbrSnk, start_time,
                              selected_paths, split_ratios, flow_id);
    cbr_srcs.push_back(cbrSrc);
    cbr_sinks.push_back(cbrSnk);
}
```

## Key Points

1. **Custom Path Selection**: You select specific paths from `net_paths[src][dest]` using `at(0)`, `at(1)`, etc.

2. **Split Ratios**: You define ratios as doubles (e.g., 0.7, 0.3). They're automatically normalized if needed.

3. **Multiple Paths**: You can use 2, 3, or more paths with corresponding split ratios.

4. **Automatic Normalization**: If ratios don't sum to 1.0, they're automatically normalized.

5. **Weighted Random Selection**: Each packet probabilistically selects a route based on the ratios.

## Customizing Split Ratios

To change the split ratios, simply modify the values:

```cpp
// Example: 80% on path 0, 20% on path 1
split_ratios.push_back(0.8);
split_ratios.push_back(0.2);

// Example: 4 paths with 40%, 30%, 20%, 10%
selected_paths.push_back(net_paths[src][dest]->at(0));
selected_paths.push_back(net_paths[src][dest]->at(1));
selected_paths.push_back(net_paths[src][dest]->at(2));
selected_paths.push_back(net_paths[src][dest]->at(3));
split_ratios.push_back(0.4);
split_ratios.push_back(0.3);
split_ratios.push_back(0.2);
split_ratios.push_back(0.1);
```

## Selecting Custom Paths

You can select any paths from the available paths:

```cpp
// Use path 0 and path 5 (not necessarily consecutive)
selected_paths.push_back(net_paths[src][dest]->at(0));
selected_paths.push_back(net_paths[src][dest]->at(5));

// Use path 2, 4, and 6
selected_paths.push_back(net_paths[src][dest]->at(2));
selected_paths.push_back(net_paths[src][dest]->at(4));
selected_paths.push_back(net_paths[src][dest]->at(6));
```

## Verification

The output confirms that:
- Flows are created with the specified split ratios
- Each flow can have different split ratios
- Multiple paths (2 or 3) are supported
- The simulation runs successfully

## Next Steps

1. Modify the split ratios in `main_cbr.cpp` to test different distributions
2. Select different paths to test various routing strategies
3. Add more flows with different split ratios
4. Analyze the log file to see traffic distribution across paths

