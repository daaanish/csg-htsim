# Custom Paths and Split Ratios in HTSIM CBR

This document explains how to use custom paths and split ratios for UDP/CBR traffic in HTSIM.

## Overview

The CBR implementation now supports:
1. **Custom Path Selection**: Choose specific paths from available topology paths
2. **Split Ratios**: Distribute traffic across multiple paths with specified ratios

## Features

### Multi-Path Support

The `CbrSrc` class now supports:
- `connect()`: Single route (backward compatible)
- `connect_multipath()`: Multiple routes with split ratios

### Split Ratio Logic

- Split ratios are normalized automatically (if they don't sum to 1.0)
- Traffic is distributed using weighted random selection
- Each packet selects a route probabilistically based on the ratios

## Usage

### Method 1: Programmatic (in main_cbr.cpp)

Uncomment the multi-path example in `main_cbr.cpp` around line 310:

```cpp
// OPTION 2: Multi-path with split ratios
if (net_paths[src][dest]->size() >= 2) {
    vector<const Route*> selected_paths;
    vector<double> split_ratios;
    
    // Select 2 paths
    selected_paths.push_back(net_paths[src][dest]->at(0));
    selected_paths.push_back(net_paths[src][dest]->at(1));
    
    // 70% on first path, 30% on second path
    split_ratios.push_back(0.7);
    split_ratios.push_back(0.3);
    
    // Create flow with multi-path
    create_cbr_flow_multipath(src, dest, top, eventlist, logfile, 
                              cbr_rate, cbrSnk, start_time,
                              selected_paths, split_ratios, flow_id);
    cbr_srcs.push_back(cbrSrc);
    cbr_sinks.push_back(cbrSnk);
}
```

### Method 2: Build Custom Routes Manually

For complete control, you can build routes manually by specifying queues and pipes:

```cpp
// Example: Build custom route
Route* custom_route = new Route();

// Add topology elements (queues and pipes) to the route
// This requires understanding your topology structure
// For fat-tree: see topology.h for element accessors

// Add sink
custom_route->push_back(cbrSnk);

// Use with single route
cbrSrc->connect(*custom_route, *cbrSnk, start_time);

// Or use with multiple routes and split ratios
vector<Route*> custom_routes;
vector<double> custom_ratios;
custom_routes.push_back(custom_route);
custom_ratios.push_back(1.0);

cbrSrc->connect_multipath(custom_routes, custom_ratios, *cbrSnk, start_time);
```

## Examples

### Example 1: 2 Paths, 70/30 Split

```cpp
vector<const Route*> paths;
vector<double> ratios;

paths.push_back(net_paths[src][dest]->at(0));  // Path 0
paths.push_back(net_paths[src][dest]->at(1));  // Path 1

ratios.push_back(0.7);  // 70% on path 0
ratios.push_back(0.3);  // 30% on path 1

create_cbr_flow_multipath(src, dest, top, eventlist, logfile,
                         cbr_rate, cbrSnk, start_time,
                         paths, ratios, flow_id);
```

### Example 2: 3 Paths, Equal Split

```cpp
vector<const Route*> paths;
vector<double> ratios;

paths.push_back(net_paths[src][dest]->at(0));
paths.push_back(net_paths[src][dest]->at(1));
paths.push_back(net_paths[src][dest]->at(2));

ratios.push_back(0.333);  // 33.3% each
ratios.push_back(0.333);
ratios.push_back(0.334);

create_cbr_flow_multipath(src, dest, top, eventlist, logfile,
                         cbr_rate, cbrSnk, start_time,
                         paths, ratios, flow_id);
```

### Example 3: 3 Paths, Custom Ratios (50/30/20)

```cpp
vector<const Route*> paths;
vector<double> ratios;

paths.push_back(net_paths[src][dest]->at(0));
paths.push_back(net_paths[src][dest]->at(1));
paths.push_back(net_paths[src][dest]->at(2));

ratios.push_back(0.5);   // 50% on path 0
ratios.push_back(0.3);   // 30% on path 1
ratios.push_back(0.2);   // 20% on path 2

create_cbr_flow_multipath(src, dest, top, eventlist, logfile,
                         cbr_rate, cbrSnk, start_time,
                         paths, ratios, flow_id);
```

## API Reference

### CbrSrc::connect_multipath()

```cpp
void connect_multipath(
    vector<route_t*>& routes,        // Vector of routes to use
    vector<double>& split_ratios,    // Split ratios (will be normalized)
    CbrSink& sink,                   // Destination sink
    simtime_picosec startTime        // Start time
);
```

**Parameters:**
- `routes`: Vector of Route pointers (must match split_ratios size)
- `split_ratios`: Traffic distribution ratios (will be normalized to sum to 1.0)
- `sink`: Destination CBR sink
- `startTime`: When to start sending

**Notes:**
- Split ratios are automatically normalized
- If ratios sum to 0, traffic is distributed equally
- Route selection uses weighted random sampling

### Helper Function: create_cbr_flow_multipath()

```cpp
void create_cbr_flow_multipath(
    uint32_t src, uint32_t dest,
    FatTreeTopology* top,
    EventList& eventlist,
    Logfile& logfile,
    linkspeed_bps rate,
    CbrSink* sink,
    simtime_picosec start_time,
    vector<const Route*>& selected_paths,
    vector<double>& split_ratios,
    uint32_t flow_id
);
```

This helper function creates a CBR source, sets up logging, and connects with multi-path.

## Accessing Topology Elements for Custom Routes

To build completely custom routes, you need access to topology elements. For fat-tree:

```cpp
// Access queues in fat-tree topology
FatTreeTopology* top = ...;

// Source queues: queues_ns_nlp[server][tor][bundle]
// Agg queues: queues_nlp_nup[tor][agg][bundle]
// Core queues: queues_nup_nc[agg][core][bundle]
// Pipes: pipes_ns_nlp, pipes_nlp_nup, pipes_nup_nc, etc.

// Note: These are private members, you may need to add accessor methods
// or make them public/friend
```

## Implementation Details

### Route Selection Algorithm

Routes are selected using weighted random sampling:
1. Normalize split ratios to sum to 1.0
2. Build cumulative distribution
3. For each packet:
   - Generate random number [0, 1)
   - Select route based on cumulative distribution

### Performance

- Route selection is O(n) where n = number of paths
- Typically n is small (2-9 paths), so overhead is minimal
- Memory overhead: O(n) per flow for storing routes and ratios

## Testing

To test multi-path functionality:

1. Modify `main_cbr.cpp` to use multi-path (uncomment the example)
2. Rebuild: `cd sim/datacenter && make htsim_cbr`
3. Run: `./htsim_cbr -nodes 54 -tiers 3 -rate 50 -end 0.1`
4. Check logs to verify traffic is distributed across paths

## Limitations

1. Split ratios are probabilistic (not deterministic per-packet)
2. Custom route building requires knowledge of topology internals
3. Currently no file-based configuration for paths/ratios (must be coded)

## Future Enhancements

Potential improvements:
- File-based path/ratio configuration
- Deterministic split ratios (round-robin or hash-based)
- Path selection based on link load/congestion
- Dynamic ratio adjustment during simulation

