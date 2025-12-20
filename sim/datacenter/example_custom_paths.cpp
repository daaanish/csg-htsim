// Example: How to use custom paths and split ratios in htsim_cbr
//
// This file demonstrates how to modify main_cbr.cpp to use custom paths and split ratios
//
// Add this code where flows are created (around line 295 in main_cbr.cpp):

/*
            // EXAMPLE 1: Use 2 paths with 70/30 split ratio
            if (net_paths[src][dest]->size() >= 2) {
                vector<const Route*> selected_paths;
                vector<double> split_ratios;
                
                // Select specific paths (path 0 and path 1)
                selected_paths.push_back(net_paths[src][dest]->at(0));
                selected_paths.push_back(net_paths[src][dest]->at(1));
                
                // 70% on first path, 30% on second path
                split_ratios.push_back(0.7);
                split_ratios.push_back(0.3);
                
                create_cbr_flow_multipath(src, dest, top, eventlist, logfile, 
                                        cbr_rate, cbrSnk, start_time,
                                        selected_paths, split_ratios, flow_id);
                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
            } else {
                // Fall back to single route if not enough paths
                cbrSrc->connect(*routeout, *cbrSnk, start_time);
                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
                cout << "Flow " << flow_id << ": " << src << " -> " << dest 
                     << " @ " << (cbr_rate / 1000000) << " Mbps" << endl;
            }
*/

/*
            // EXAMPLE 2: Use 3 paths with equal split (33.3% each)
            if (net_paths[src][dest]->size() >= 3) {
                vector<const Route*> selected_paths;
                vector<double> split_ratios;
                
                selected_paths.push_back(net_paths[src][dest]->at(0));
                selected_paths.push_back(net_paths[src][dest]->at(1));
                selected_paths.push_back(net_paths[src][dest]->at(2));
                
                split_ratios.push_back(0.333);
                split_ratios.push_back(0.333);
                split_ratios.push_back(0.334);
                
                create_cbr_flow_multipath(src, dest, top, eventlist, logfile, 
                                        cbr_rate, cbrSnk, start_time,
                                        selected_paths, split_ratios, flow_id);
                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
            } else {
                cbrSrc->connect(*routeout, *cbrSnk, start_time);
                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
            }
*/

/*
            // EXAMPLE 3: Build custom route manually (for advanced users)
            // You can manually construct a Route by specifying queues and pipes
            
            // First, get access to topology elements
            // Note: This requires understanding the topology structure
            // For fat-tree, paths consist of:
            // - Source queue: queues_ns_nlp[src][tor][bundle]
            // - Pipe: pipes_ns_nlp[src][tor][bundle]
            // - Agg queue: queues_nlp_nup[tor][agg][bundle]
            // - Pipe: pipes_nlp_nup[tor][agg][bundle]
            // - Core queue (if 3-tier): queues_nup_nc[agg][core][bundle]
            // - Pipe: pipes_nup_nc[agg][core][bundle]
            // - ... and back down
            
            Route* custom_route = new Route();
            
            // Add your custom path elements here
            // Example: custom_route->push_back(some_queue);
            //          custom_route->push_back(some_pipe);
            // ... etc
            
            custom_route->push_back(cbrSnk);
            
            // Use single route
            cbrSrc->connect(*custom_route, *cbrSnk, start_time);
            
            // Or use with split ratios
            vector<Route*> custom_routes;
            vector<double> custom_ratios;
            custom_routes.push_back(custom_route);
            custom_ratios.push_back(1.0);
            
            cbrSrc->connect_multipath(custom_routes, custom_ratios, *cbrSnk, start_time);
*/

