// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
// HTSIM CBR (UDP-like) Driver
// Based on main_ndp.cpp, simplified for constant bit rate traffic

#include "config.h"
#include <sstream>
#include <iostream>
#include <string.h>
#include <math.h>
#include <fstream>
#include <vector>
#include <algorithm>
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
#include "json_topology.h"
#include "firstfit.h"
#include <list>
#include <map>

using std::vector;
using std::min;
using std::cout;
using std::endl;
using std::stringstream;
using std::string;

// Simulation params
#define PRINT_PATHS 0
#define PERIODIC 0
#include "main.h"

// Default parameters
uint32_t RTT = 1;  // per link delay in microseconds
int DEFAULT_NODES = 8;
int DEFAULT_QUEUE_SIZE = 15; // in packets

string strRouteStrategy = "";
EventList eventlist;
// Optional override to force a specific single-path index for all flows
int g_single_path_index = -1;
// Optional custom multipath parameters
int g_max_paths = 0; // 0 = default (min(3, available))
vector<double> g_split_ratios; // if provided via -split, use these
// Optional: list ECMP paths for a given src/dst and exit
bool g_list_paths = false;
int g_list_src = -1;
int g_list_dst = -1;
// Optional: list top-K shortest paths by hops
bool g_list_kshort = false;
int g_kshort_src = -1;
int g_kshort_dst = -1;
int g_kshort_k = 0;
// Convenience: list hosts and resolve names
bool g_list_hosts = false;
bool g_list_kshort_names = false;
std::string g_kshort_src_name;
std::string g_kshort_dst_name;
int g_kshort_k_names = 0;

// Print out queue path for a Route (used if you enable PRINT_PATHS)
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

// Print a Route to stdout with human-readable queue names (odd hops are queues)
void print_route_stdout(const Route* rt) {
    // Generic printing (legacy). Will be overridden by enhanced JSON formatting elsewhere.
    for (uint32_t i = 0; i < rt->size(); i++) {
        PacketSink* ps = rt->at(i);
        if (ps) {
            // Try dynamic cast to Queue or Pipe for name
            Queue* q = dynamic_cast<Queue*>(ps);
            Pipe* p = dynamic_cast<Pipe*>(ps);
            if (q) cout << q->nodename();
            else if (p) cout << p->nodename();
            else cout << "sink";
        } else {
            cout << "NULL";
        }
        if (i+1 < rt->size()) cout << " -> ";
    }
    cout << endl;
}

// Enhanced formatter: show only queues (skip pipes), as src->dst names, assuming forced naming q_src_dst
static void print_route_json(const Route* rt) {
    bool first=true;
    for (uint32_t i = 0; i < rt->size(); i++) {
        Queue* q = dynamic_cast<Queue*>(rt->at(i));
        if (!q) continue; // ignore non-queues
        std::string name = q->nodename();
        if (!first) cout << " | ";
        cout << name; // already q_src_dst
        first=false;
    }
    if (first) cout << "(no queues)"; // nothing printed
    cout << endl;
}

// Helper function to create CBR flow with custom paths and split ratios
// This function USES the caller-provided CbrSrc* and CbrSink* (no ownership change)
void create_cbr_flow_multipath(
    uint32_t src, uint32_t dest,
    FatTreeTopology* top,
    EventList& eventlist,
    Logfile& logfile,
    CbrSrc* cbrSrc,               // <-- use caller's source
    linkspeed_bps rate,
    CbrSink* sink,               // <-- caller's sink
    simtime_picosec start_time,
    const vector<const Route*>& selected_paths,
    const vector<double>& split_ratios,
    uint32_t flow_id
) {
    // Create Route objects from selected paths and append sink
    vector<Route*> routes;
    for (size_t i = 0; i < selected_paths.size(); i++) {
        Route* route = new Route(*(selected_paths[i])); // copy
        route->push_back(sink);
        routes.push_back(route);
    }

    // Connect with multi-path using the existing CbrSrc
    cbrSrc->connect_multipath(routes, split_ratios, *sink, start_time);

    // Print summary to console for quick verification
    cout << "Flow " << flow_id << ": " << src << " -> " << dest
         << " @ " << (rate / 1000000) << " Mbps with " << routes.size()
         << " paths, ratios: ";
    for (size_t i = 0; i < split_ratios.size(); i++) {
        cout << split_ratios[i];
        if (i < split_ratios.size() - 1) cout << ", ";
    }
    cout << endl;
}

// Helper for single-path flow; also uses caller-provided source/sink
void create_cbr_flow_singlepath(
    uint32_t src, uint32_t dest,
    FatTreeTopology* top,
    EventList& eventlist,
    Logfile& logfile,
    CbrSrc* cbrSrc,
    linkspeed_bps rate,
    CbrSink* sink,
    simtime_picosec start_time,
    const Route* selected_path,
    uint32_t flow_id
) {
    Route* routeout = new Route(*selected_path); // copy
    routeout->push_back(sink);
    cbrSrc->connect(*routeout, *sink, start_time);

    cout << "Flow " << flow_id << ": " << src << " -> " << dest
         << " @ " << (rate / 1000000) << " Mbps (single path)" << endl;
}

int main(int argc, char **argv) {
    // Simulation setup
    eventlist.setEndtime(timeFromSec(1.01));  // default 1 second simulation
    Clock c(timeFromSec(50 / 100.), eventlist);

    // Default parameters
    mem_b queuesize = memFromPkt(DEFAULT_QUEUE_SIZE);
    // Base speeds (can be overridden via CLI)
    // host_nic_speed controls server<->ToR links (tier 0). internal_link_speed controls fabric links (tiers >= 1).
    linkspeed_bps host_nic_speed = speedFromMbps((uint64_t)HOST_NIC); // default to HOST_NIC from config.h
    linkspeed_bps internal_link_speed = speedFromMbps((uint64_t)5000); // default 5 Gbps fabric
    bool custom_downlink_speeds = false; // when true, we'll set per-tier speeds and pass 0 to constructor
    int no_of_nodes = DEFAULT_NODES;
    int no_of_tiers = 2;
    linkspeed_bps default_cbr_rate = speedFromMbps((uint64_t)1000);  // default 100 Mbps per flow
    simtime_picosec hop_latency = timeFromUs((uint32_t)1);
    simtime_picosec switch_latency = timeFromUs((uint32_t)0);
    int seed = time(NULL);  // Use current time for different random sequence each run (was: 13)
    double end_time_sec = 1.01;

    string filename("logout.dat");
    string traffic_file = "";
    RouteStrategy route_strategy = SCATTER_RANDOM;
    // Queue types (network switches and sender)
    queue_type qt = COMPOSITE;  // default network queue type
    queue_type sender_qt = PRIORITY;  // sender queue type (must be PRIORITY, FAIR_PRIO, or SWIFT_SCHEDULER)

    // Toggle for multipath vs. single-path mode (can also be set via -multipath flag)
    bool USE_MULTIPATH = false;
    // Queue logging config
    string queue_log_mode = "none"; // none|simple|sampling|empty
    double queue_log_period_us = 10.0;

    // Parse command-line arguments
    int i = 1;
    const char* json_topo_file = NULL; // optional JSON topology file
    while (i < argc) {
        if (!strcmp(argv[i], "-o")) {
            filename = argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-nodes")) {
            no_of_nodes = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-tiers")) {
            no_of_tiers = atoi(argv[i+1]);
            assert(no_of_tiers == 2 || no_of_tiers == 3);
            i++;
        } else if (!strcmp(argv[i], "-list_paths")) {
            // Usage: -list_paths <src> <dst>
            if (i + 2 >= argc) {
                cout << "Usage: -list_paths <src> <dst>" << endl;
                exit(1);
            }
            g_list_paths = true;
            g_list_src = atoi(argv[i+1]);
            g_list_dst = atoi(argv[i+2]);
            i += 2;
        } else if (!strcmp(argv[i], "-list_hosts")) {
            g_list_hosts = true;
        } else if (!strcmp(argv[i], "-list_kshort")) {
            // Usage: -list_kshort <src> <dst> <k>
            if (i + 3 >= argc) {
                cout << "Usage: -list_kshort <src> <dst> <k>" << endl;
                exit(1);
            }
            g_list_kshort = true;
            g_kshort_src = atoi(argv[i+1]);
            g_kshort_dst = atoi(argv[i+2]);
            g_kshort_k = atoi(argv[i+3]);
            i += 3;
        } else if (!strcmp(argv[i], "-list_kshort_names")) {
            // Usage: -list_kshort_names <srcName> <dstName> <k>
            if (i + 3 >= argc) {
                cout << "Usage: -list_kshort_names <srcName> <dstName> <k>" << endl;
                exit(1);
            }
            g_list_kshort_names = true;
            g_kshort_src_name = argv[i+1];
            g_kshort_dst_name = argv[i+2];
            g_kshort_k_names = atoi(argv[i+3]);
            i += 3;
        } else if (!strcmp(argv[i], "-q")) {
            queuesize = memFromPkt(atoi(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-tm")) {
            traffic_file = argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-strat")) {
            strRouteStrategy = argv[i+1];
            if (strRouteStrategy == "rand" || strRouteStrategy == "random") {
                route_strategy = SCATTER_RANDOM;
            } else if (strRouteStrategy == "perm" || strRouteStrategy == "permutation") {
                route_strategy = SCATTER_PERMUTE;
            } else if (strRouteStrategy == "single") {
                route_strategy = SINGLE_PATH;
            } else if (strRouteStrategy == "ecmp") {
                route_strategy = SCATTER_ECMP;
            }
            i++;
        } else if (!strcmp(argv[i], "-json_topo")) {
            json_topo_file = argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-rate")) {
            default_cbr_rate = speedFromMbps(atof(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-linkspeed") || !strcmp(argv[i], "-fabric_mbps")) {
            // Set fabric (tiers >= 1) link speed in Mbps
            internal_link_speed = speedFromMbps(atof(argv[i+1]));
            custom_downlink_speeds = true;
            i++;
        } else if (!strcmp(argv[i], "-host_nic_mbps")) {
            // Set host NIC (tier 0 downlink) speed in Mbps
            host_nic_speed = speedFromMbps(atof(argv[i+1]));
            custom_downlink_speeds = true;
            i++;
        } else if (!strcmp(argv[i], "-end")) {
            end_time_sec = atof(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-seed")) {
            seed = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-hop_latency")) {
            hop_latency = timeFromUs(atof(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-switch_latency")) {
            switch_latency = timeFromUs(atof(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-multipath")) {
            // command-line flag to enable multipath mode
            USE_MULTIPATH = true;
        } else if (!strcmp(argv[i], "-single_path_index")) {
            // force a specific path index for SINGLE_PATH strategy
            g_single_path_index = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-paths")) {
            // limit number of ECMP paths used for multipath
            g_max_paths = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-split")) {
            // custom split ratios for multipath, comma-separated (e.g., 0.7,0.3)
            g_split_ratios.clear();
            string ratios = argv[i+1];
            i++;
            string num;
            stringstream ss(ratios);
            while (getline(ss, num, ',')) {
                if (!num.empty()) {
                    g_split_ratios.push_back(atof(num.c_str()));
                }
            }
            // normalize ratios to sum to 1.0 if possible
            double sum = 0.0; for (double r : g_split_ratios) sum += r;
            if (sum > 0) {
                for (size_t k = 0; k < g_split_ratios.size(); k++)
                    g_split_ratios[k] /= sum;
            }
        } else if (!strcmp(argv[i], "-queue_log")) {
            queue_log_mode = argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-queue_period_us")) {
            queue_log_period_us = atof(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-queue_type")) {
            // Select switch queue type for network links
            string qt_str = argv[i+1];
            i++;
            if (qt_str == "random") qt = RANDOM;
            else if (qt_str == "composite") qt = COMPOSITE;
            else if (qt_str == "ecn") qt = ECN;
            else if (qt_str == "composite_ecn") qt = COMPOSITE_ECN;
            else if (qt_str == "lossless") qt = LOSSLESS;
            else if (qt_str == "lossless_input") qt = LOSSLESS_INPUT;
            else if (qt_str == "lossless_input_ecn") qt = LOSSLESS_INPUT_ECN;
            else if (qt_str == "ecn_prio") qt = ECN_PRIO;
            else if (qt_str == "priority" || qt_str == "prio") qt = PRIORITY;
            else {
                cout << "Unknown -queue_type '" << qt_str << "', defaulting to COMPOSITE" << endl;
                qt = COMPOSITE;
            }
        } else {
            cout << "Unknown option: " << argv[i] << endl;
            exit(1);
        }
        i++;
    }

    srand(seed);
    srandom(seed);

    cout << "Logging to " << filename << endl;
    if (!json_topo_file) {
        // Legacy fat-tree parameters (these may be overridden once topology is built)
        cout << "Fat-tree requested: nodes=" << no_of_nodes << " tiers=" << no_of_tiers << endl;
    } else {
        // In JSON mode the node count and any tier concept will come from the file
        cout << "JSON topology mode (nodes and tiers will be derived from file)" << endl;
    }
    cout << "Queue size: " << queuesize / 1000 << " KB" << endl;
    cout << "Default CBR rate: " << default_cbr_rate / 1000000 << " Mbps" << endl;
    cout << "Simulation end time: " << end_time_sec << " seconds" << endl;
    cout << "Multipath mode: " << (USE_MULTIPATH ? "ENABLED" : "DISABLED") << endl;

    eventlist.setEndtime(timeFromSec(end_time_sec));

    // Setup logfile
    Logfile logfile(filename, eventlist);
    logfile.setStartTime(timeFromSec(0));

    simtime_picosec log_period = timeFromMs(1);
    CbrSinkLoggerSampling sink_logger = CbrSinkLoggerSampling(log_period, eventlist);
    logfile.addLogger(sink_logger);

    // Create topology
    FatTreeTopology::set_tiers(no_of_tiers);

    // Configure QueueLoggerFactory based on CLI
    QueueLoggerFactory* qlf = NULL;
    if (queue_log_mode == "simple") {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_SIMPLE, eventlist);
    } else if (queue_log_mode == "sampling") {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_SAMPLING, eventlist);
        qlf->set_sample_period(timeFromUs(queue_log_period_us));
    } else if (queue_log_mode == "empty") {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_EMPTY, eventlist);
        qlf->set_sample_period(timeFromUs(queue_log_period_us));
    }

    if (custom_downlink_speeds) {
        // Override per-tier speeds: ToR downlink uses host NIC, fabric uses internal_link_speed
        FatTreeTopology::set_downlink_speeds(host_nic_speed, internal_link_speed, internal_link_speed);
    }

    Topology* topo_base = nullptr;
    FatTreeTopology* top_fat = nullptr;
    if (json_topo_file) {
        cout << "Loading JSON topology from " << json_topo_file << endl;
        // Pass queue logger factory, queue type, and queuesize so JSON topology respects -queue_type parameter
        JsonTopology* jt = new JsonTopology(&logfile, &eventlist, qlf, qt, queuesize);
        if (!jt->load(json_topo_file)) {
            cerr << "Failed to load JSON topology file; exiting" << endl;
            return 1;
        }
        topo_base = jt;
    } else {
        top_fat = new FatTreeTopology(
            no_of_nodes,
            custom_downlink_speeds ? (linkspeed_bps)0 : internal_link_speed,
            queuesize,
            qlf,  // queue logger factory
            &eventlist,
            NULL,  // no first-fit
            qt,  // queue type
            hop_latency,  // link latency
            switch_latency,  // switch latency
            sender_qt  // sender queue type
        );
        topo_base = top_fat;
    }
    // Maintain legacy variable name 'top' for existing helper function signatures
    FatTreeTopology* top = top_fat; 

    no_of_nodes = topo_base->no_of_nodes();
    if (json_topo_file) {
        cout << "Nodes: " << no_of_nodes << endl;
    } else {
        cout << "Actual nodes: " << no_of_nodes << endl;
    }

    // If requested: list host indices (JSON topology only)
    if (g_list_hosts) {
        if (JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base)) {
            const vector<string>& hosts = jt->get_hosts();
            cout << "Host indices (zero-based):" << endl;
            for (size_t idx = 0; idx < hosts.size(); ++idx) {
                cout << idx << ": " << hosts[idx] << endl;
            }
            return 0;
        } else {
            cout << "-list_hosts requires a JSON topology (-json_topo)." << endl;
            return 1;
        }
    }

    // Emit queue ID->name mappings into the logfile preamble so parsers can resolve IDs
    // The topology already assigns human-readable names (setName) to all queues.
    // We write them here for all tiers and directions.
    if (top_fat) {
        auto write_queue_names = [&](vector< vector< vector<BaseQueue*> > >& q3){
            for (size_t i = 0; i < q3.size(); i++) {
                for (size_t j = 0; j < q3[i].size(); j++) {
                    for (size_t k = 0; k < q3[i][j].size(); k++) {
                        BaseQueue* q = q3[i][j][k];
                        if (q) logfile.writeName(*q);
                    }
                }
            }
        };
        write_queue_names(top_fat->queues_nlp_ns);
        write_queue_names(top_fat->queues_ns_nlp);
        write_queue_names(top_fat->queues_nlp_nup);
        write_queue_names(top_fat->queues_nup_nlp);
        write_queue_names(top_fat->queues_nup_nc);
        write_queue_names(top_fat->queues_nc_nup);
    }

    // If requested: enumerate ECMP paths for a given src/dst and exit
    if (g_list_paths || g_list_kshort || g_list_kshort_names) {
        int ls = -1, ld = -1;
        if (g_list_paths || g_list_kshort) {
            ls = g_list_paths ? g_list_src : g_kshort_src;
            ld = g_list_paths ? g_list_dst : g_kshort_dst;
        } else {
            // Resolve names via JSON topology
            JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base);
            if (!jt) {
                cout << "-list_kshort_names requires a JSON topology (-json_topo)." << endl;
                return 1;
            }
            const vector<string>& hosts = jt->get_hosts();
            auto resolve = [&](const std::string& name)->int{
                for (size_t i = 0; i < hosts.size(); ++i) {
                    if (hosts[i] == name) return (int)i;
                }
                return -1;
            };
            ls = resolve(g_kshort_src_name);
            ld = resolve(g_kshort_dst_name);
            if (ls < 0 || ld < 0) {
                cout << "Unknown host name(s): src='" << g_kshort_src_name << "' dst='" << g_kshort_dst_name << "'" << endl;
                cout << "Use -list_hosts to see the available names." << endl;
                return 1;
            }
        }
        if (ls < 0 || ld < 0 || ls >= (int)no_of_nodes || ld >= (int)no_of_nodes) {
            cout << "Invalid src/dst for -list_paths. Nodes must be in [0," << (no_of_nodes-1) << "]" << endl;
            return 1;
        }
        vector<const Route*>* paths = nullptr;
        if (g_list_kshort || g_list_kshort_names) {
            // Prefer JSON topology k-shortest implementation when available
            if (JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base)) {
                int K = std::max(1, g_list_kshort_names ? g_kshort_k_names : g_kshort_k);
                paths = jt->get_k_shortest_paths(ls, ld, (size_t)K);
            } else {
                // Fallback: take first K ECMP paths if available
                vector<const Route*>* all = topo_base->get_paths(ls, ld);
                if (all) {
                    paths = new vector<const Route*>();
                    int K = std::max(1, g_list_kshort_names ? g_kshort_k_names : g_kshort_k);
                    for (int idx = 0; idx < K && idx < (int)all->size(); ++idx) paths->push_back(all->at(idx));
                }
            }
            int Kprint = std::max(1, g_list_kshort_names ? g_kshort_k_names : g_kshort_k);
            cout << "Top-" << Kprint << " shortest paths (by hops) from host " << ls
                 << " to host " << ld << ":" << endl;
        } else {
            paths = topo_base->get_paths(ls, ld);
            cout << "ECMP shortest paths from host " << ls << " to host " << ld
                 << " (count=" << (paths?paths->size():0) << ")" << endl;
        }
        if (!paths || paths->empty()) {
            cout << "No paths found from " << ls << " to " << ld << endl;
            return 0;
        }
        cout << "Index : Path (queue hops)" << endl;
        for (size_t idx = 0; idx < paths->size(); idx++) {
            cout << "[" << idx << "] ";
            // For JSON topology we have descriptive q_src_dst names
            if (dynamic_cast<JsonTopology*>(topo_base)) print_route_json(paths->at(idx));
            else print_route_stdout(paths->at(idx));
        }
        cout << endl;
        cout << "Use these indices with TM token 'paths_idx' (e.g., paths_idx 0,1) or CLI -single_path_index <i>." << endl;
        return 0;
    }

    // Path storage
    vector<const Route*>*** net_paths;
    net_paths = new vector<const Route*>**[no_of_nodes];
    for (uint32_t i = 0; i < (uint32_t)no_of_nodes; i++) {
        net_paths[i] = new vector<const Route*>*[no_of_nodes];
        for (uint32_t j = 0; j < (uint32_t)no_of_nodes; j++)
            net_paths[i][j] = NULL;
    }

    // Read traffic matrix
    ConnectionMatrix* conns = new ConnectionMatrix(no_of_nodes);

    if (!traffic_file.empty()) {
        cout << "Loading connection matrix from " << traffic_file << endl;
        if (!conns->load(traffic_file.c_str())) {
            cout << "Failed to load connection matrix " << traffic_file << endl;
            exit(-1);
        }
    } else {
        cout << "No traffic matrix specified, using permutation" << endl;
        conns->setPermutation(no_of_nodes / 2);
    }

    if (conns->N != (uint32_t)no_of_nodes) {
        cout << "Connection matrix number of nodes is " << conns->N << " while I am using " << no_of_nodes << endl;
        exit(-1);
    }

    // Handle link failures specified in the connection matrix
    for (size_t c = 0; c < conns->failures.size(); c++) {
        failure* crt = conns->failures.at(c);
        cout << "Adding link failure switch type " << crt->switch_type
             << " Switch ID " << crt->switch_id
             << " link ID " << crt->link_id << endl;
        if (top) {
            top->add_failed_link(crt->switch_type, crt->switch_id, crt->link_id);
        }
    }

    // Get all connections - prefer connection objects for more flexibility
    vector<connection*>* all_conns = conns->getAllConnections();

    // Create CBR flows
    uint32_t flow_id = 0;
    list<CbrSrc*> cbr_srcs;
    list<CbrSink*> cbr_sinks;
    struct SinkInfo { CbrSink* snk; int src; int dst; uint32_t flow_id; };
    vector<SinkInfo> sink_infos;

    // If we have connection objects, use them (more flexible - supports start times, etc.)
    if (all_conns && all_conns->size() > 0) {
        cout << "Using connection objects format (" << all_conns->size() << " connections)" << endl;

        for (size_t cidx = 0; cidx < all_conns->size(); cidx++) {
            connection* crt = all_conns->at(cidx);
            int src = crt->src;
            int dest = crt->dst;
            flow_id++;

            // Get ECMP shortest paths and, if TM provides indices on JSON topo, also compute K-shortest for selection
            if (!net_paths[src][dest]) {
                net_paths[src][dest] = topo_base->get_paths(src, dest);
            }
            vector<const Route*>* sel_paths = net_paths[src][dest];
            JsonTopology* jt_sel = dynamic_cast<JsonTopology*>(topo_base);
            if (jt_sel && !crt->path_indices.empty()) {
                // Allow selecting non-shortest alternatives via TM indices
                sel_paths = jt_sel->get_k_shortest_paths(src, dest, 8 /*K*/);
            }

            if (!sel_paths || sel_paths->size() == 0) {
                cout << "Warning: No path found from " << src << " to " << dest << endl;
                continue;
            }

            // Use default rate for now (could extend connection struct to support rate)
            linkspeed_bps cbr_rate = default_cbr_rate;

            // Create CBR source and sink (one per flow)
            CbrSrc* cbrSrc = new CbrSrc(
                eventlist,
                cbr_rate,
                timeFromMs(0),  // active time (0 = always on)
                timeFromMs(0)   // idle time
            );
            // If TM specifies a flow size, configure the CbrSrc to stop after that many bytes
            if (crt->size > 0) {
                cbrSrc->set_flow_size_bytes((uint64_t)crt->size);
            }

            CbrSink* cbrSnk = new CbrSink();

            sink_logger.monitorSink(cbrSnk);

            // Set names for logging (unique)
            stringstream src_name;
            src_name << "cbr_src_" << src << "_" << dest << "_" << flow_id;
            cbrSrc->setName(src_name.str());
            logfile.writeName(*cbrSrc);

            stringstream snk_name;
            snk_name << "cbr_sink_" << src << "_" << dest << "_" << flow_id;
            cbrSnk->setName(snk_name.str());
            logfile.writeName(*cbrSnk);

            // Select route based on strategy; allow per-flow explicit index via TM when provided
            size_t path_choice = 0;
            if (!crt->path_indices.empty()) {
                path_choice = ((size_t)std::max(0, crt->path_indices[0])) % sel_paths->size();
            } else if (route_strategy == SCATTER_RANDOM || route_strategy == SCATTER_PERMUTE) {
                path_choice = rand() % sel_paths->size();
            } else {
                if (g_single_path_index >= 0) {
                    path_choice = ((size_t)g_single_path_index) % sel_paths->size();
                } else {
                    path_choice = flow_id % sel_paths->size();
                }
            }

            // Connect flow - use connection start time if specified
            simtime_picosec start_time = (crt->start != NO_START) ? crt->start : timeFromMs(0);

            // Decide single-path or multipath based on CLI or per-flow TM attributes
            bool flow_requests_multipath = (crt->paths > 1) || (!crt->split_ratios.empty()) || (!crt->byte_thresholds.empty()) || (!crt->explicit_routes.empty());
            bool flow_uses_thresholds = !crt->byte_thresholds.empty();
            size_t requested_paths = (crt->paths > 0) ? crt->paths : 0;
            vector<double> flow_split = crt->split_ratios; // may be empty
            vector<uint64_t> flow_thresholds = crt->byte_thresholds; // may be empty

            if ((USE_MULTIPATH || flow_requests_multipath) && sel_paths->size() >= 2) {
                // MULTIPATH: choose up to N paths (configurable). If TM provides explicit routes/indices, honor them.
                vector<const Route*> selected_paths;
                vector<double> split_ratios;

                // choose number of paths: priority TM->CLI->default
                size_t default_max = min((size_t)3, sel_paths->size());
                size_t max_paths = default_max;
                if (g_max_paths > 0) max_paths = min((size_t)g_max_paths, sel_paths->size());
                if (requested_paths > 0) max_paths = min((size_t)requested_paths, sel_paths->size());
                
                // Check for explicit_routes first (Gurobi's actual paths)
                if (!crt->explicit_routes.empty()) {
                    // Use explicit routes from Gurobi - these are queue name lists
                    JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base);
                    if (jt) {
                        for (size_t p = 0; p < crt->explicit_routes.size(); p++) {
                            Route* r = jt->build_route_from_queue_names(crt->explicit_routes[p]);
                            if (r) {
                                selected_paths.push_back(r);
                            } else {
                                cout << "Warning: Failed to build explicit route " << p 
                                     << " for flow " << src << "->" << dest << endl;
                            }
                        }
                        max_paths = selected_paths.size();
                    } else {
                        cout << "Warning: explicit_routes requires JsonTopology" << endl;
                    }
                } else if (!crt->path_indices.empty()) {
                    // Use provided indices, up to max_paths
                    for (size_t p = 0; p < max_paths && p < crt->path_indices.size(); p++) {
                        size_t idx = (size_t)std::max(0, crt->path_indices[p]);
                        idx %= sel_paths->size();
                        selected_paths.push_back(sel_paths->at(idx));
                    }
                    // If fewer provided than max_paths, fall back to first ECMPs for the remainder
                    for (size_t p = selected_paths.size(); p < max_paths; p++) {
                        selected_paths.push_back(sel_paths->at(p));
                    }
                } else {
                    // Default: take first max_paths ECMP routes
                    for (size_t p = 0; p < max_paths; p++) {
                        selected_paths.push_back(sel_paths->at(p));
                    }
                }

                // Use per-flow split ratios if provided; else CLI; else equal
                if (!flow_split.empty()) {
                    split_ratios.assign(max_paths, 0.0);
                    for (size_t p = 0; p < max_paths; p++) {
                        split_ratios[p] = (p < flow_split.size()) ? flow_split[p] : 0.0;
                    }
                    double sumr = 0.0; for (double r : split_ratios) sumr += r;
                    if (sumr == 0.0) split_ratios.assign(max_paths, 1.0 / (double)max_paths);
                } else if (!g_split_ratios.empty()) {
                    split_ratios.assign(max_paths, 0.0);
                    for (size_t p = 0; p < max_paths; p++) {
                        split_ratios[p] = (p < g_split_ratios.size()) ? g_split_ratios[p] : 0.0;
                    }
                    // If sum is zero (e.g., bad input), fall back to equal
                    double sumr = 0.0; for (double r : split_ratios) sumr += r;
                    if (sumr == 0.0) split_ratios.assign(max_paths, 1.0 / (double)max_paths);
                } else {
                    split_ratios.assign(max_paths, 1.0 / (double)max_paths);
                }

                // Create flow with multi-path (either split ratios or thresholds)
                if (top) {
                    create_cbr_flow_multipath(src, dest, top, eventlist,
                                             logfile,
                                             cbrSrc, cbr_rate, cbrSnk, start_time,
                                             selected_paths, split_ratios, flow_id);
                } else {
                    // JSON topology: selected_paths already include sink appended here
                    vector<Route*> routes;
                    for (auto* base: selected_paths) {
                        Route* r = new Route(*base);
                        r->push_back(cbrSnk);
                        routes.push_back(r);
                    }
                    
                    // Use threshold-based switching if thresholds provided, else split ratios
                    if (flow_uses_thresholds && !flow_thresholds.empty()) {
                        cbrSrc->connect_multipath_thresholds(routes, flow_thresholds, *cbrSnk, start_time);
                        cout << "Flow " << flow_id << ": " << src << " -> " << dest
                             << " @ " << (cbr_rate / 1000000) << " Mbps with " << routes.size()
                             << " JSON paths, thresholds: ";
                        for (size_t i = 0; i < flow_thresholds.size(); i++) {
                            cout << flow_thresholds[i] << (i+1<flow_thresholds.size()?", ":"");
                        }
                        cout << " bytes\n";
                    } else {
                        cbrSrc->connect_multipath(routes, split_ratios, *cbrSnk, start_time);
                        cout << "Flow " << flow_id << ": " << src << " -> " << dest
                             << " @ " << (cbr_rate / 1000000) << " Mbps with " << routes.size()
                             << " JSON paths, ratios: ";
                        for (size_t i = 0; i < split_ratios.size(); i++) {
                            cout << split_ratios[i] << (i+1<split_ratios.size()?", ":"\n");
                        }
                    }
                }

                // Keep track of source and sink objects (for later cleanup / stats)
                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
                sink_infos.push_back({cbrSnk, src, dest, flow_id});
            } else {
                // SINGLE path (honors TM-provided path index if any)
                const Route* chosen = sel_paths->at(path_choice);
                create_cbr_flow_singlepath(src, dest, top, eventlist, logfile,
                                           cbrSrc, cbr_rate, cbrSnk, start_time,
                                           chosen, flow_id);

                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
                sink_infos.push_back({cbrSnk, (int)src, (int)dest, flow_id});
            }
        }
    } else {
        // Fall back to simple map format
        cout << "Using simple connections map format" << endl;
        map<uint32_t, vector<uint32_t>*>::iterator it;

        for (it = conns->connections.begin(); it != conns->connections.end(); it++) {
            uint32_t src = (*it).first;
            vector<uint32_t>* destinations = (*it).second;

            for (uint32_t dst_id = 0; dst_id < destinations->size(); dst_id++) {
                uint32_t dest = destinations->at(dst_id);
                flow_id++;

                // Get paths if not already computed
                if (!net_paths[src][dest]) {
                    net_paths[src][dest] = topo_base->get_paths(src, dest);
                }

                if (!net_paths[src][dest] || net_paths[src][dest]->size() == 0) {
                    cout << "Warning: No path found from " << src << " to " << dest << endl;
                    continue;
                }

                // Create CBR source and sink
                linkspeed_bps cbr_rate = default_cbr_rate;
                CbrSrc* cbrSrc = new CbrSrc(
                    eventlist,
                    cbr_rate,
                    timeFromMs(0),  // active time (0 = always on)
                    timeFromMs(0)   // idle time
                );

                CbrSink* cbrSnk = new CbrSink();
            
                sink_logger.monitorSink(cbrSnk);

                // Set names for logging
                stringstream src_name;
                src_name << "cbr_src_" << src << "_" << dest << "_" << flow_id;
                cbrSrc->setName(src_name.str());
                logfile.writeName(*cbrSrc);

                stringstream snk_name;
                snk_name << "cbr_sink_" << src << "_" << dest << "_" << flow_id;
                cbrSnk->setName(snk_name.str());
                logfile.writeName(*cbrSnk);

                // Select route based on strategy
                size_t path_choice = 0;
                if (route_strategy == SCATTER_RANDOM || route_strategy == SCATTER_PERMUTE) {
                    path_choice = rand() % net_paths[src][dest]->size();
                } else {
                    if (g_single_path_index >= 0) {
                        path_choice = ((size_t)g_single_path_index) % net_paths[src][dest]->size();
                    } else {
                        path_choice = flow_id % net_paths[src][dest]->size();
                    }
                }

                // Connect flow: multipath vs single
                simtime_picosec start_time = timeFromMs(0);

                bool flow_requests_multipath2 = false; // not available in map format
                if ((USE_MULTIPATH || flow_requests_multipath2) && net_paths[src][dest]->size() >= 2) {
                    vector<const Route*> selected_paths;
                    vector<double> split_ratios;
                    size_t default_max = min((size_t)3, net_paths[src][dest]->size());
                    size_t max_paths = (g_max_paths > 0) ? min((size_t)g_max_paths, net_paths[src][dest]->size()) : default_max;
                    for (size_t p = 0; p < max_paths; p++)
                        selected_paths.push_back(net_paths[src][dest]->at(p));

                    if (!g_split_ratios.empty()) {
                        split_ratios.assign(max_paths, 0.0);
                        for (size_t p = 0; p < max_paths; p++) {
                            split_ratios[p] = (p < g_split_ratios.size()) ? g_split_ratios[p] : 0.0;
                        }
                        double sumr = 0.0; for (double r : split_ratios) sumr += r;
                        if (sumr == 0.0) split_ratios.assign(max_paths, 1.0 / (double)max_paths);
                    } else {
                        split_ratios.assign(max_paths, 1.0 / (double)max_paths);
                    }

                    if (top) {
                        create_cbr_flow_multipath(src, dest, top, eventlist,
                                                  logfile,
                                                  cbrSrc, cbr_rate, cbrSnk, start_time,
                                                  selected_paths, split_ratios, flow_id);
                    } else {
                        vector<Route*> routes;
                        for (auto* base: selected_paths) {
                            Route* r = new Route(*base);
                            r->push_back(cbrSnk);
                            routes.push_back(r);
                        }
                        cbrSrc->connect_multipath(routes, split_ratios, *cbrSnk, start_time);
                        cout << "Flow " << flow_id << ": " << src << " -> " << dest
                             << " @ " << (cbr_rate / 1000000) << " Mbps with " << routes.size()
                             << " JSON paths, ratios: ";
                        for (size_t i = 0; i < split_ratios.size(); i++) {
                            cout << split_ratios[i] << (i+1<split_ratios.size()?", ":"\n");
                        }
                    }
                } else {
                    Route* routeout = new Route(*(net_paths[src][dest]->at(path_choice)));
                    routeout->push_back(cbrSnk);
                    cbrSrc->connect(*routeout, *cbrSnk, start_time);
                    cout << "Flow " << flow_id << ": " << src << " -> " << dest
                         << " @ " << (cbr_rate / 1000000) << " Mbps (single path)" << endl;
                }

                cbr_srcs.push_back(cbrSrc);
                cbr_sinks.push_back(cbrSnk);
            }
        }
    }

    cout << "Total flows created: " << flow_id << endl;

    // Record simulation parameters
    logfile.write("# pktsize=" + to_string(Packet::data_packet_size()) + " bytes");
    logfile.write("# nodes=" + to_string(no_of_nodes));
    logfile.write("# linkspeed=" + to_string(internal_link_speed/1000000) + " Mbps");
    logfile.write("# hostnicrate = " + to_string(host_nic_speed/1000000) + " Mbps");
    logfile.write("# fabricrate = " + to_string(internal_link_speed/1000000) + " Mbps");
    logfile.write("# default_rate=" + to_string(default_cbr_rate/1000000) + " Mbps");
    logfile.write("# flows=" + to_string(flow_id));

    // Run simulation
    cout << "Starting simulation..." << endl;
    while (eventlist.doNextEvent()) {
    }

    cout << "Simulation complete!" << endl;

    // Print per-flow stats: bytes sent (source) vs bytes received (sink)
    {
        auto itSrc = cbr_srcs.begin();
        for (size_t i = 0; i < sink_infos.size() && itSrc != cbr_srcs.end(); i++, ++itSrc) {
            auto &si = sink_infos[i];
            CbrSrc* src = *itSrc;
            uint64_t sent = src ? src->bytes_emitted() : 0;
            uint64_t rcvd = si.snk ? si.snk->cumulative_ack() : 0;
            // Parse-friendly summary
            cout << "FLOW_STATS flow=" << si.flow_id
                 << " src=" << si.src
                 << " dst=" << si.dst
                 << " sent_bytes=" << sent
                 << " received_bytes=" << rcvd << "\n";
            // Keep legacy sink summary for quick eyeballing
            cout << "CBR Sink " << (i+1)
                 << " (flow " << si.flow_id << ": " << si.src << "->" << si.dst
                 << ", name=" << si.snk->str() << ") received bytes: "
                 << rcvd << "\n";
        }
    }

    return 0;
}
