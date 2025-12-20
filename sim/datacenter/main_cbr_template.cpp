// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
// HTSIM CBR (UDP-like) Driver - Starter Template
// Based on main_ndp.cpp, simplified for constant bit rate traffic

#include "config.h"
#include <sstream>
#include <iostream>
#include <string.h>
#include <math.h>
#include "network.h"
#include "randomqueue.h"
#include "pipe.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "clock.h"
#include "cbr.h"           // CBR source and sink
#include "cbrpacket.h"     // CBR packets
#include "topology.h"
#include "connection_matrix.h"
#include "fat_tree_topology.h"
#include <list>

// Simulation params
#define PRINT_PATHS 0
#define PERIODIC 0
#include "main.h"

// Default parameters
uint32_t RTT = 1;  // per link delay in microseconds
int DEFAULT_NODES = 16;
int DEFAULT_QUEUE_SIZE = 15; // in packets

string strRouteStrategy = "";
EventList eventlist;

void print_path(std::ofstream &paths, const Route* rt) {
    for (uint32_t i = 1; i < rt->size() - 1; i += 2) {
        RandomQueue* q = (RandomQueue*)rt->at(i);
        if (q != NULL)
            paths << q->str() << " ";
        else
            paths << "NULL ";
    }
    paths << endl;
}

int main(int argc, char **argv) {
    // Simulation setup
    eventlist.setEndtime(timeFromSec(1.01));  // 1 second simulation
    Clock c(timeFromSec(50 / 100.), eventlist);
    
    // Default parameters
    mem_b queuesize = memFromPkt(DEFAULT_QUEUE_SIZE);
    linkspeed_bps linkspeed = speedFromMbps((uint64_t)HOST_NIC);
    int no_of_nodes = DEFAULT_NODES;
    int no_of_tiers = 2;
    int cwnd = 15;
    
    string filename("logout.dat");
    string traffic_file = "";
    
    // Parse command-line arguments
    int i = 1;
    while (i < argc) {
        if (!strcmp(argv[i], "-o")) {
            filename = argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-nodes")) {
            no_of_nodes = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-tiers")) {
            no_of_tiers = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-q")) {
            queuesize = memFromPkt(atoi(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-tm")) {
            traffic_file = argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-strat")) {
            strRouteStrategy = argv[i+1];
            i++;
        } else {
            cout << "Unknown option: " << argv[i] << endl;
            exit(1);
        }
        i++;
    }
    
    cout << "Logging to " << filename << endl;
    cout << "Nodes: " << no_of_nodes << endl;
    cout << "Tiers: " << no_of_tiers << endl;
    cout << "Queue size: " << queuesize / 1000 << " KB" << endl;
    
    // Setup logfile
    Logfile logfile(filename, eventlist);
    logfile.setStartTime(timeFromSec(0));
    
    // TODO: Add CBR-specific loggers here
    // For now, use generic logger
    TrafficLoggerSimple traffic_logger;
    logfile.addLogger(traffic_logger);
    
    // Create topology
    FatTreeTopology* top = new FatTreeTopology(
        no_of_nodes, 
        linkspeed, 
        queuesize, 
        NULL,  // no queue logger for now
        &eventlist, 
        NULL,  // no first-fit
        RANDOM,  // random path selection
        0
    );
    
    no_of_nodes = top->no_of_nodes();
    cout << "Actual nodes: " << no_of_nodes << endl;
    
    // Path storage
    vector<const Route*>*** net_paths;
    net_paths = new vector<const Route*>**[no_of_nodes];
    for (uint32_t i = 0; i < no_of_nodes; i++) {
        net_paths[i] = new vector<const Route*>*[no_of_nodes];
        for (uint32_t j = 0; j < no_of_nodes; j++)
            net_paths[i][j] = NULL;
    }
    
    // TODO: Read traffic matrix from file
    // For now, create simple permutation
    ConnectionMatrix* conns = new ConnectionMatrix(no_of_nodes);
    
    if (traffic_file.empty()) {
        cout << "No traffic matrix specified, using permutation" << endl;
        conns->setPermutation(no_of_nodes / 2);
    } else {
        // TODO: Implement traffic matrix file parsing
        // Format: src dest rate_mbps start_time duration
        cout << "Traffic matrix file parsing not yet implemented" << endl;
        exit(1);
    }
    
    // Create CBR flows
    uint32_t flow_id = 0;
    map<uint32_t, vector<uint32_t>*>::iterator it;
    
    for (it = conns->connections.begin(); it != conns->connections.end(); it++) {
        uint32_t src = (*it).first;
        vector<uint32_t>* destinations = (*it).second;
        
        for (uint32_t dst_id = 0; dst_id < destinations->size(); dst_id++) {
            uint32_t dest = destinations->at(dst_id);
            flow_id++;
            
            cout << "Flow " << flow_id << ": " << src << " -> " << dest << endl;
            
            // Get paths
            if (!net_paths[src][dest])
                net_paths[src][dest] = top->get_paths(src, dest);
            
            // Create CBR source and sink
            linkspeed_bps cbr_rate = speedFromMbps(100);  // 100 Mbps per flow
            CbrSrc* cbrSrc = new CbrSrc(
                eventlist,
                cbr_rate,
                timeFromMs(0),  // active time (0 = always on)
                timeFromMs(0)   // idle time
            );
            
            CbrSink* cbrSnk = new CbrSink();
            
            // Set names for logging
            stringstream src_name;
            src_name << "cbr_src_" << src << "_" << dest << "_" << flow_id;
            cbrSrc->setName(src_name.str());
            logfile.writeName(*cbrSrc);
            
            stringstream snk_name;
            snk_name << "cbr_sink_" << src << "_" << dest << "_" << flow_id;
            cbrSnk->setName(snk_name.str());
            logfile.writeName(*cbrSnk);
            
            // Select route (random for now)
            size_t path_choice = rand() % net_paths[src][dest]->size();
            Route* routeout = new Route(*(net_paths[src][dest]->at(path_choice)));
            routeout->push_back(cbrSnk);
            
            // Connect flow
            simtime_picosec start_time = timeFromMs(0);
            cbrSrc->connect(*routeout, *cbrSnk, start_time);
            
            // TODO: Add to sink logger for monitoring
        }
    }
    
    cout << "Total flows created: " << flow_id << endl;
    
    // Record simulation parameters
    logfile.write("# pktsize=" + to_string(Packet::data_packet_size()) + " bytes");
    logfile.write("# nodes=" + to_string(no_of_nodes));
    logfile.write("# linkspeed=" + to_string(linkspeed/1000000) + " Mbps");
    
    // Run simulation
    cout << "Starting simulation..." << endl;
    while (eventlist.doNextEvent()) {
    }
    
    cout << "Simulation complete!" << endl;
    return 0;
}
