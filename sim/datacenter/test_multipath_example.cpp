// Quick Test: Enable multi-path with split ratios
//
// To test this, replace the single-route connection code in main_cbr.cpp
// (around line 314) with this code:

/*
            // Connect flow - use connection start time if specified
            simtime_picosec start_time = (crt->start != NO_START) ? crt->start : timeFromMs(0);
            
            // Test multi-path with split ratios for flows from even-numbered sources
            if (src % 2 == 0 && net_paths[src][dest]->size() >= 2) {
                // Use multi-path for even source nodes
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
            } else {
                // Use single route for odd source nodes
                Route* routeout = new Route(*(net_paths[src][dest]->at(path_choice)));
                routeout->push_back(cbrSnk);
                cbrSrc->connect(*routeout, *cbrSnk, start_time);
                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
                cout << "Flow " << flow_id << ": " << src << " -> " << dest 
                     << " @ " << (cbr_rate / 1000000) << " Mbps" << endl;
            }
*/

