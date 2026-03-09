// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
//
// HTSIM CBR (UDP-like) Driver
//
// Supports fat-tree and arbitrary JSON topologies, single-path and multi-path
// routing (probabilistic split ratios, byte-threshold switching, explicit
// Gurobi routes), traffic-engineering demand/admitted metadata, per-flow rate
// overrides, and post-simulation telemetry (FLOW_STATS / PAIR_STATS /
// GLOBAL_STATS).

#include "config.h"
#include <sstream>
#include <iostream>
#include <string.h>
#include <math.h>
#include <fstream>
#include <vector>
#include <algorithm>
#include <iomanip>
#include <list>
#include <map>
#include <utility>

#include "network.h"
#include "randomqueue.h"
#include "pipe.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "clock.h"
#include "cbr.h"
#include "cbrpacket.h"
#include "topology.h"
#include "connection_matrix.h"
#include "fat_tree_topology.h"
#include "json_topology.h"
#include "firstfit.h"

using std::vector;
using std::min;
using std::cout;
using std::cerr;
using std::endl;
using std::stringstream;
using std::string;
using std::fixed;
using std::setprecision;
using std::pair;
using std::make_pair;
using std::map;

#define PRINT_PATHS 0
#define PERIODIC 0
#include "main.h"

// ============================================================================
//  Global state
// ============================================================================

uint32_t RTT = 1;
static const int DEFAULT_NODES = 8;
static const int DEFAULT_QUEUE_SIZE = 15;   // packets

string strRouteStrategy = "";
EventList eventlist;

// CLI-configurable globals
static int    g_single_path_index = -1;     // force a specific ECMP path index
static int    g_max_paths = 0;              // 0 = default (min(3, available))
static vector<double> g_split_ratios;       // if provided via -split

// Path / host listing modes (print and exit)
static bool   g_list_paths = false;
static int    g_list_src = -1, g_list_dst = -1;
static bool   g_list_kshort = false;
static int    g_kshort_src = -1, g_kshort_dst = -1, g_kshort_k = 0;
static bool   g_list_hosts = false;
static bool   g_list_kshort_names = false;
static string g_kshort_src_name, g_kshort_dst_name;
static int    g_kshort_k_names = 0;

// ============================================================================
//  Utility: route printing
// ============================================================================

// Print a Route to an ofstream (legacy format -- odd hops are queues).
static void print_path(std::ofstream& paths, const Route* rt) {
    for (uint32_t i = 1; i < rt->size() - 1; i += 2) {
        RandomQueue* q = (RandomQueue*)rt->at(i);
        if (q) paths << q->str() << " ";
        else   paths << "NULL ";
    }
    paths << endl;
}

// Print a Route to stdout with dynamic_cast for name resolution.
static void print_route_stdout(const Route* rt) {
    for (uint32_t i = 0; i < rt->size(); i++) {
        PacketSink* ps = rt->at(i);
        if (ps) {
            Queue* q = dynamic_cast<Queue*>(ps);
            Pipe*  p = dynamic_cast<Pipe*>(ps);
            if (q)       cout << q->nodename();
            else if (p)  cout << p->nodename();
            else         cout << "sink";
        } else {
            cout << "NULL";
        }
        if (i + 1 < rt->size()) cout << " -> ";
    }
    cout << endl;
}

// Print only queue names (JSON-topology style: q_src_dst | q_x_y | ...).
static void print_route_json(const Route* rt) {
    bool first = true;
    for (uint32_t i = 0; i < rt->size(); i++) {
        Queue* q = dynamic_cast<Queue*>(rt->at(i));
        if (!q) continue;
        if (!first) cout << " | ";
        cout << q->nodename();
        first = false;
    }
    if (first) cout << "(no queues)";
    cout << endl;
}

// ============================================================================
//  Per-flow bookkeeping (for post-sim telemetry)
// ============================================================================

struct FlowInfo {
    CbrSrc*  src;
    CbrSink* snk;
    int      src_id;
    int      dst_id;
    uint32_t flow_id;
    double   demand;        // d_st  (bytes, metadata only)
    double   admitted;      // b_st  (bytes, from TE solver)
};

// ============================================================================
//  Flow creation helpers
// ============================================================================

// Resolve the vector of split ratios to use: per-flow TM > CLI -split > equal.
static vector<double> resolve_split_ratios(size_t n_paths,
                                           const vector<double>& flow_split)
{
    vector<double> ratios(n_paths, 0.0);
    const vector<double>& source = flow_split.empty() ? g_split_ratios : flow_split;

    if (!source.empty()) {
        for (size_t i = 0; i < n_paths; i++)
            ratios[i] = (i < source.size()) ? source[i] : 0.0;
        double s = 0; for (double r : ratios) s += r;
        if (s == 0.0) ratios.assign(n_paths, 1.0 / (double)n_paths);
    } else {
        ratios.assign(n_paths, 1.0 / (double)n_paths);
    }
    return ratios;
}

// Determine how many paths to use: per-flow TM > CLI -paths > default(3).
static size_t resolve_max_paths(size_t available,
                                int flow_requested)
{
    size_t def = min((size_t)3, available);
    size_t mp = def;
    if (g_max_paths > 0) mp = min((size_t)g_max_paths, available);
    if (flow_requested > 0) mp = min((size_t)flow_requested, available);
    return mp;
}

// Select path routes from the available set (explicit routes, indices, or default).
static vector<const Route*> select_paths(
    const connection* crt,
    vector<const Route*>* sel_paths,
    Topology* topo_base,
    size_t max_paths,
    CbrSink* snk)
{
    vector<const Route*> selected;

    // 1. Explicit routes (from Gurobi).
    if (!crt->explicit_routes.empty()) {
        JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base);
        if (jt) {
            for (size_t p = 0; p < crt->explicit_routes.size(); p++) {
                Route* r = jt->build_route_from_queue_names(crt->explicit_routes[p]);
                if (r)  selected.push_back(r);
                else    cout << "Warning: explicit route " << p << " failed for "
                             << crt->src << "->" << crt->dst << endl;
            }
            return selected;
        }
        cout << "Warning: explicit_routes requires JsonTopology" << endl;
    }

    // 2. Explicit path indices.
    if (!crt->path_indices.empty()) {
        for (size_t p = 0; p < max_paths && p < crt->path_indices.size(); p++) {
            size_t idx = (size_t)std::max(0, crt->path_indices[p]) % sel_paths->size();
            selected.push_back(sel_paths->at(idx));
        }
        // Pad remaining with first ECMP routes.
        for (size_t p = selected.size(); p < max_paths; p++)
            selected.push_back(sel_paths->at(p));
        return selected;
    }

    // 3. Default: first N ECMP routes.
    for (size_t p = 0; p < max_paths; p++)
        selected.push_back(sel_paths->at(p));
    return selected;
}

// Connect a single-path CBR flow.
static void connect_single(CbrSrc* src, CbrSink* snk,
                            const Route* base_route,
                            simtime_picosec start_time,
                            linkspeed_bps rate, uint32_t flow_id,
                            int s, int d)
{
    Route* r = new Route(*base_route);
    r->push_back(snk);
    src->connect(*r, *snk, start_time);
    cout << "Flow " << flow_id << ": " << s << " -> " << d
         << " @ " << (rate / 1000000) << " Mbps (single path)" << endl;
}

// Connect a multi-path CBR flow with probabilistic split ratios.
static void connect_multipath_split(CbrSrc* src, CbrSink* snk,
                                     const vector<const Route*>& paths,
                                     const vector<double>& ratios,
                                     simtime_picosec start_time,
                                     linkspeed_bps rate, uint32_t flow_id,
                                     int s, int d)
{
    vector<Route*> routes;
    for (auto* base : paths) {
        Route* r = new Route(*base);
        r->push_back(snk);
        routes.push_back(r);
    }
    vector<double> mutable_ratios = ratios;
    src->connect_multipath(routes, mutable_ratios, *snk, start_time);

    cout << "Flow " << flow_id << ": " << s << " -> " << d
         << " @ " << (rate / 1000000) << " Mbps with " << routes.size()
         << " paths, ratios: ";
    for (size_t i = 0; i < ratios.size(); i++) {
        cout << ratios[i];
        if (i + 1 < ratios.size()) cout << ", ";
    }
    cout << endl;
}

// Connect a multi-path CBR flow with byte-threshold switching.
static void connect_multipath_thresholds(CbrSrc* src, CbrSink* snk,
                                          const vector<const Route*>& paths,
                                          const vector<uint64_t>& thresholds,
                                          simtime_picosec start_time,
                                          linkspeed_bps rate, uint32_t flow_id,
                                          int s, int d)
{
    vector<Route*> routes;
    for (auto* base : paths) {
        Route* r = new Route(*base);
        r->push_back(snk);
        routes.push_back(r);
    }
    src->connect_multipath_thresholds(routes, thresholds, *snk, start_time);

    cout << "Flow " << flow_id << ": " << s << " -> " << d
         << " @ " << (rate / 1000000) << " Mbps with " << routes.size()
         << " paths, thresholds: ";
    for (size_t i = 0; i < thresholds.size(); i++) {
        cout << thresholds[i];
        if (i + 1 < thresholds.size()) cout << ", ";
    }
    cout << " bytes" << endl;
}

// ============================================================================
//  Telemetry output
// ============================================================================

static void print_telemetry(const vector<FlowInfo>& flows) {
    double   total_demand   = 0;
    double   total_admitted = 0;
    uint64_t total_delivered = 0;
    uint64_t total_sent      = 0;

    struct PairStats { double demand{0}; double admitted{0}; uint64_t sent{0}; uint64_t delivered{0}; };
    map<pair<int,int>, PairStats> pair_stats;

    cout << "\n========== PER-FLOW TELEMETRY ==========" << endl;
    cout << "flow | src | dst | demand_bytes | admitted_bytes"
         << " | sent_bytes | delivered_bytes | delivery_ratio" << endl;
    cout << "-----+-----+-----+--------------+----------------"
         << "+------------+-----------------+---------------" << endl;

    for (auto& fi : flows) {
        uint64_t sent = fi.src ? fi.src->bytes_emitted() : 0;
        uint64_t rcvd = fi.snk ? fi.snk->cumulative_ack() : 0;
        double ratio = (fi.admitted > 0) ? ((double)rcvd / fi.admitted) : 0.0;

        cout << "FLOW_STATS"
             << " flow=" << fi.flow_id
             << " src="  << fi.src_id
             << " dst="  << fi.dst_id
             << " demand_bytes="    << (uint64_t)fi.demand
             << " admitted_bytes="  << (uint64_t)fi.admitted
             << " sent_bytes="      << sent
             << " delivered_bytes=" << rcvd
             << " delivery_ratio="  << fixed << setprecision(6) << ratio
             << "\n";

        total_demand   += fi.demand;
        total_admitted += fi.admitted;
        total_delivered += rcvd;
        total_sent      += sent;

        auto key = make_pair(fi.src_id, fi.dst_id);
        pair_stats[key].demand   += fi.demand;
        pair_stats[key].admitted += fi.admitted;
        pair_stats[key].sent     += sent;
        pair_stats[key].delivered += rcvd;
    }

    cout << "\n========== PER-PAIR TELEMETRY ==========" << endl;
    for (auto& kv : pair_stats) {
        uint64_t lost = (kv.second.sent > kv.second.delivered)
                        ? (kv.second.sent - kv.second.delivered) : 0;
        double delivery_ratio = (kv.second.admitted > 0)
                       ? ((double)kv.second.delivered / kv.second.admitted) : 0.0;
        double loss_ratio = (kv.second.sent > 0)
                       ? ((double)lost / (double)kv.second.sent) : 0.0;
        cout << "PAIR_STATS"
             << " src=" << kv.first.first
             << " dst=" << kv.first.second
             << " demand_bytes="    << (uint64_t)kv.second.demand
             << " admitted_bytes="  << (uint64_t)kv.second.admitted
             << " sent_bytes="      << kv.second.sent
             << " delivered_bytes=" << kv.second.delivered
             << " lost_bytes="      << lost
             << " delivery_ratio="  << fixed << setprecision(6) << delivery_ratio
             << " loss_ratio="      << fixed << setprecision(6) << loss_ratio
             << "\n";
    }

    uint64_t total_lost = (total_sent > total_delivered)
                         ? (total_sent - total_delivered) : 0;
    double global_delivery = (total_admitted > 0)
                          ? ((double)total_delivered / total_admitted) : 0.0;
    double global_loss = (total_sent > 0)
                          ? ((double)total_lost / (double)total_sent) : 0.0;
    cout << "\n========== GLOBAL SUMMARY ===========" << endl;
    cout << "GLOBAL_STATS"
         << " total_demand_bytes="    << (uint64_t)total_demand
         << " total_admitted_bytes="  << (uint64_t)total_admitted
         << " total_sent_bytes="      << total_sent
         << " total_delivered_bytes=" << total_delivered
         << " total_lost_bytes="      << total_lost
         << " global_delivery_ratio=" << fixed << setprecision(6) << global_delivery
         << " global_loss_ratio="     << fixed << setprecision(6) << global_loss
         << "\n";
    cout << "====================================\n";
}

// ============================================================================
//  CLI argument parsing
// ============================================================================

struct SimConfig {
    string      filename{"logout.dat"};
    string      traffic_file;
    const char* json_topo_file{nullptr};

    int  no_of_nodes{DEFAULT_NODES};
    int  no_of_tiers{2};
    int  seed{0};           // 0 = use time(NULL)

    linkspeed_bps host_nic_speed;
    linkspeed_bps fabric_speed;
    bool          custom_speeds{false};

    linkspeed_bps default_cbr_rate;
    mem_b         queuesize;
    double        end_time_sec{1.01};

    simtime_picosec hop_latency;
    simtime_picosec switch_latency;

    bool       use_multipath{false};
    queue_type qt{COMPOSITE};
    queue_type sender_qt{PRIORITY};

    string queue_log_mode{"none"};
    double queue_log_period_us{10.0};

    RouteStrategy route_strategy{SCATTER_RANDOM};
};

static void parse_args(int argc, char** argv, SimConfig& cfg) {
    cfg.host_nic_speed   = speedFromMbps((uint64_t)HOST_NIC);
    cfg.fabric_speed     = speedFromMbps((uint64_t)5000);
    cfg.default_cbr_rate = speedFromMbps((uint64_t)1000);
    cfg.queuesize        = memFromPkt(DEFAULT_QUEUE_SIZE);
    cfg.hop_latency      = timeFromUs((uint32_t)1);
    cfg.switch_latency   = timeFromUs((uint32_t)0);

    int i = 1;
    while (i < argc) {
        // --- Output / topology ---
        if (!strcmp(argv[i], "-o")) {
            cfg.filename = argv[++i];
        } else if (!strcmp(argv[i], "-nodes")) {
            cfg.no_of_nodes = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "-tiers")) {
            cfg.no_of_tiers = atoi(argv[++i]);
            assert(cfg.no_of_tiers == 2 || cfg.no_of_tiers == 3);
        } else if (!strcmp(argv[i], "-json_topo")) {
            cfg.json_topo_file = argv[++i];
        } else if (!strcmp(argv[i], "-tm")) {
            cfg.traffic_file = argv[++i];
        }
        // --- Simulation parameters ---
        else if (!strcmp(argv[i], "-rate")) {
            cfg.default_cbr_rate = speedFromMbps(atof(argv[++i]));
        } else if (!strcmp(argv[i], "-linkspeed") || !strcmp(argv[i], "-fabric_mbps")) {
            cfg.fabric_speed = speedFromMbps(atof(argv[++i]));
            cfg.custom_speeds = true;
        } else if (!strcmp(argv[i], "-host_nic_mbps")) {
            cfg.host_nic_speed = speedFromMbps(atof(argv[++i]));
            cfg.custom_speeds = true;
        } else if (!strcmp(argv[i], "-q")) {
            cfg.queuesize = memFromPkt(atoi(argv[++i]));
        } else if (!strcmp(argv[i], "-end")) {
            cfg.end_time_sec = atof(argv[++i]);
        } else if (!strcmp(argv[i], "-seed")) {
            cfg.seed = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "-hop_latency")) {
            cfg.hop_latency = timeFromUs(atof(argv[++i]));
        } else if (!strcmp(argv[i], "-switch_latency")) {
            cfg.switch_latency = timeFromUs(atof(argv[++i]));
        }
        // --- Routing / multipath ---
        else if (!strcmp(argv[i], "-strat")) {
            strRouteStrategy = argv[++i];
            if      (strRouteStrategy == "rand"  || strRouteStrategy == "random")      cfg.route_strategy = SCATTER_RANDOM;
            else if (strRouteStrategy == "perm"  || strRouteStrategy == "permutation") cfg.route_strategy = SCATTER_PERMUTE;
            else if (strRouteStrategy == "single")                                     cfg.route_strategy = SINGLE_PATH;
            else if (strRouteStrategy == "ecmp")                                       cfg.route_strategy = SCATTER_ECMP;
        } else if (!strcmp(argv[i], "-multipath")) {
            cfg.use_multipath = true;
        } else if (!strcmp(argv[i], "-single_path_index")) {
            g_single_path_index = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "-paths")) {
            g_max_paths = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "-split")) {
            g_split_ratios.clear();
            string ratios_str = argv[++i];
            stringstream ss(ratios_str);
            string num;
            while (getline(ss, num, ',')) {
                if (!num.empty()) g_split_ratios.push_back(atof(num.c_str()));
            }
            double s = 0; for (double r : g_split_ratios) s += r;
            if (s > 0) for (auto& r : g_split_ratios) r /= s;
        }
        // --- Queue config ---
        else if (!strcmp(argv[i], "-queue_type")) {
            string qt_str = argv[++i];
            if      (qt_str == "random")            cfg.qt = RANDOM;
            else if (qt_str == "composite")         cfg.qt = COMPOSITE;
            else if (qt_str == "ecn")               cfg.qt = ECN;
            else if (qt_str == "composite_ecn")     cfg.qt = COMPOSITE_ECN;
            else if (qt_str == "lossless")          cfg.qt = LOSSLESS;
            else if (qt_str == "lossless_input")    cfg.qt = LOSSLESS_INPUT;
            else if (qt_str == "lossless_input_ecn") cfg.qt = LOSSLESS_INPUT_ECN;
            else if (qt_str == "ecn_prio")          cfg.qt = ECN_PRIO;
            else if (qt_str == "priority" || qt_str == "prio") cfg.qt = PRIORITY;
            else { cout << "Unknown -queue_type '" << qt_str << "', defaulting to COMPOSITE" << endl; }
        } else if (!strcmp(argv[i], "-queue_log")) {
            cfg.queue_log_mode = argv[++i];
        } else if (!strcmp(argv[i], "-queue_period_us")) {
            cfg.queue_log_period_us = atof(argv[++i]);
        }
        // --- Path / host listing (print and exit) ---
        else if (!strcmp(argv[i], "-list_paths")) {
            if (i + 2 >= argc) { cout << "Usage: -list_paths <src> <dst>" << endl; exit(1); }
            g_list_paths = true;
            g_list_src = atoi(argv[++i]);
            g_list_dst = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "-list_hosts")) {
            g_list_hosts = true;
        } else if (!strcmp(argv[i], "-list_kshort")) {
            if (i + 3 >= argc) { cout << "Usage: -list_kshort <src> <dst> <k>" << endl; exit(1); }
            g_list_kshort = true;
            g_kshort_src = atoi(argv[++i]);
            g_kshort_dst = atoi(argv[++i]);
            g_kshort_k   = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "-list_kshort_names")) {
            if (i + 3 >= argc) { cout << "Usage: -list_kshort_names <srcName> <dstName> <k>" << endl; exit(1); }
            g_list_kshort_names = true;
            g_kshort_src_name = argv[++i];
            g_kshort_dst_name = argv[++i];
            g_kshort_k_names  = atoi(argv[++i]);
        }
        // --- Unknown ---
        else {
            cout << "Unknown option: " << argv[i] << endl;
            exit(1);
        }
        i++;
    }

    if (cfg.seed == 0) cfg.seed = time(NULL);
}

// ============================================================================
//  Path listing (print-and-exit modes)
// ============================================================================

static int handle_list_modes(Topology* topo_base, int no_of_nodes) {
    if (g_list_hosts) {
        JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base);
        if (!jt) { cout << "-list_hosts requires -json_topo" << endl; return 1; }
        const vector<string>& hosts = jt->get_hosts();
        cout << "Host indices (zero-based):" << endl;
        for (size_t i = 0; i < hosts.size(); i++)
            cout << i << ": " << hosts[i] << endl;
        return 0;
    }

    // Resolve src/dst for all path-listing modes.
    int ls = -1, ld = -1;
    if (g_list_paths)  { ls = g_list_src;   ld = g_list_dst; }
    if (g_list_kshort) { ls = g_kshort_src; ld = g_kshort_dst; }
    if (g_list_kshort_names) {
        JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base);
        if (!jt) { cout << "-list_kshort_names requires -json_topo" << endl; return 1; }
        const vector<string>& hosts = jt->get_hosts();
        for (size_t i = 0; i < hosts.size(); i++) {
            if (hosts[i] == g_kshort_src_name) ls = (int)i;
            if (hosts[i] == g_kshort_dst_name) ld = (int)i;
        }
        if (ls < 0 || ld < 0) {
            cout << "Unknown host name(s): src='" << g_kshort_src_name
                 << "' dst='" << g_kshort_dst_name << "'" << endl;
            cout << "Use -list_hosts to see available names." << endl;
            return 1;
        }
    }

    if (ls < 0 || ld < 0 || ls >= no_of_nodes || ld >= no_of_nodes) {
        cout << "Invalid src/dst. Nodes must be in [0," << (no_of_nodes - 1) << "]" << endl;
        return 1;
    }

    vector<const Route*>* paths = nullptr;
    if (g_list_kshort || g_list_kshort_names) {
        int K = std::max(1, g_list_kshort_names ? g_kshort_k_names : g_kshort_k);
        if (JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base))
            paths = jt->get_k_shortest_paths(ls, ld, (size_t)K);
        else {
            vector<const Route*>* all = topo_base->get_paths(ls, ld);
            if (all) {
                paths = new vector<const Route*>();
                for (int idx = 0; idx < K && idx < (int)all->size(); idx++)
                    paths->push_back(all->at(idx));
            }
        }
        cout << "Top-" << K << " shortest paths from host " << ls
             << " to host " << ld << ":" << endl;
    } else {
        paths = topo_base->get_paths(ls, ld);
        cout << "ECMP paths from host " << ls << " to host " << ld
             << " (count=" << (paths ? paths->size() : 0) << ")" << endl;
    }

    if (!paths || paths->empty()) {
        cout << "No paths found." << endl;
        return 0;
    }
    cout << "Index : Path (queue hops)" << endl;
    for (size_t idx = 0; idx < paths->size(); idx++) {
        cout << "[" << idx << "] ";
        if (dynamic_cast<JsonTopology*>(topo_base)) print_route_json(paths->at(idx));
        else print_route_stdout(paths->at(idx));
    }
    cout << "\nUse these indices with TM token 'paths_idx' or CLI -single_path_index." << endl;
    return 0;
}

// ============================================================================
//  Create a single CBR flow from a connection object
// ============================================================================

static FlowInfo create_flow(
    connection* crt,
    uint32_t flow_id,
    Topology* topo_base,
    vector<const Route*>** cached_paths,
    EventList& evlist,
    Logfile& logfile,
    CbrSinkLoggerSampling& sink_logger,
    linkspeed_bps default_rate,
    bool use_multipath,
    RouteStrategy route_strategy)
{
    int src  = crt->src;
    int dest = crt->dst;

    // --- Path lookup -------------------------------------------------------
    if (!cached_paths[src * topo_base->no_of_nodes() + dest])
        cached_paths[src * topo_base->no_of_nodes() + dest] = topo_base->get_paths(src, dest);

    vector<const Route*>* sel_paths = cached_paths[src * topo_base->no_of_nodes() + dest];

    // For explicit path indices on JSON topology, fetch K-shortest.
    JsonTopology* jt = dynamic_cast<JsonTopology*>(topo_base);
    if (jt && !crt->path_indices.empty())
        sel_paths = jt->get_k_shortest_paths(src, dest, 4);

    if (!sel_paths || sel_paths->empty()) {
        cout << "Warning: No path from " << src << " to " << dest << endl;
        return {nullptr, nullptr, src, dest, flow_id, 0, 0};
    }

    // --- Per-flow rate -----------------------------------------------------
    linkspeed_bps rate = (crt->rate_mbps > 0) ? speedFromMbps(crt->rate_mbps)
                                               : default_rate;

    // --- Create source & sink ----------------------------------------------
    CbrSrc* cbrSrc = new CbrSrc(evlist, rate, timeFromMs(0), timeFromMs(0));
    CbrSink* cbrSnk = new CbrSink();

    // Flow size: 'size' is the per-flow volume.  'admitted' is pair-level
    // metadata; only use it as fallback when size is absent.
    uint64_t active_bytes = 0;
    if (crt->size > 0)          active_bytes = (uint64_t)crt->size;
    else if (crt->admitted > 0) active_bytes = (uint64_t)crt->admitted;
    if (active_bytes > 0)       cbrSrc->set_flow_size_bytes(active_bytes);

    sink_logger.monitorSink(cbrSnk);

    // Names for logging.
    stringstream ss;
    ss << "cbr_src_" << src << "_" << dest << "_" << flow_id;
    cbrSrc->setName(ss.str());
    logfile.writeName(*cbrSrc);

    ss.str(""); ss.clear();
    ss << "cbr_sink_" << src << "_" << dest << "_" << flow_id;
    cbrSnk->setName(ss.str());
    logfile.writeName(*cbrSnk);

    // --- Start time --------------------------------------------------------
    simtime_picosec start_time = (crt->start != NO_START) ? crt->start : timeFromMs(0);

    // --- Single-path vs multi-path -----------------------------------------
    bool wants_multipath = use_multipath ||
                           (crt->paths > 1) ||
                           !crt->split_ratios.empty() ||
                           !crt->byte_thresholds.empty() ||
                           !crt->explicit_routes.empty();

    if (wants_multipath && sel_paths->size() >= 2) {
        size_t max_paths = resolve_max_paths(sel_paths->size(), crt->paths);
        if (!crt->explicit_routes.empty()) max_paths = crt->explicit_routes.size();

        vector<const Route*> chosen = select_paths(crt, sel_paths, topo_base,
                                                   max_paths, cbrSnk);
        if (!crt->byte_thresholds.empty()) {
            connect_multipath_thresholds(cbrSrc, cbrSnk, chosen,
                                          crt->byte_thresholds,
                                          start_time, rate, flow_id, src, dest);
        } else {
            vector<double> ratios = resolve_split_ratios(chosen.size(),
                                                         crt->split_ratios);
            connect_multipath_split(cbrSrc, cbrSnk, chosen, ratios,
                                     start_time, rate, flow_id, src, dest);
        }
    } else {
        // Single path.
        size_t path_choice = 0;
        if (!crt->path_indices.empty()) {
            path_choice = (size_t)std::max(0, crt->path_indices[0]) % sel_paths->size();
        } else if (route_strategy == SCATTER_RANDOM || route_strategy == SCATTER_PERMUTE) {
            path_choice = rand() % sel_paths->size();
        } else if (g_single_path_index >= 0) {
            path_choice = (size_t)g_single_path_index % sel_paths->size();
        } else {
            path_choice = flow_id % sel_paths->size();
        }
        connect_single(cbrSrc, cbrSnk, sel_paths->at(path_choice),
                        start_time, rate, flow_id, src, dest);
    }

    return {cbrSrc, cbrSnk, src, dest, flow_id, crt->demand, crt->admitted};
}

// ============================================================================
//  main()
// ============================================================================

int main(int argc, char** argv)
{
    // --- Parse CLI ----------------------------------------------------------
    SimConfig cfg;
    parse_args(argc, argv, cfg);

    srand(cfg.seed);
    srandom(cfg.seed);

    eventlist.setEndtime(timeFromSec(cfg.end_time_sec));
    Clock c(timeFromSec(50 / 100.), eventlist);

    // --- Print config summary ----------------------------------------------
    cout << "Logging to " << cfg.filename << endl;
    if (cfg.json_topo_file)
        cout << "JSON topology mode" << endl;
    else
        cout << "Fat-tree: nodes=" << cfg.no_of_nodes
             << " tiers=" << cfg.no_of_tiers << endl;
    cout << "Queue size: " << cfg.queuesize / 1000 << " KB" << endl;
    cout << "Default CBR rate: " << cfg.default_cbr_rate / 1000000 << " Mbps" << endl;
    cout << "Sim end: " << cfg.end_time_sec << "s" << endl;
    cout << "Multipath: " << (cfg.use_multipath ? "ENABLED" : "DISABLED") << endl;

    // --- Logfile & sink logger ---------------------------------------------
    Logfile logfile(cfg.filename, eventlist);
    logfile.setStartTime(timeFromSec(0));

    CbrSinkLoggerSampling sink_logger(timeFromMs(1), eventlist);
    logfile.addLogger(sink_logger);

    // --- Queue logger factory ----------------------------------------------
    QueueLoggerFactory* qlf = nullptr;
    if (cfg.queue_log_mode == "simple") {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_SIMPLE, eventlist);
    } else if (cfg.queue_log_mode == "sampling") {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_SAMPLING, eventlist);
        qlf->set_sample_period(timeFromUs(cfg.queue_log_period_us));
    } else if (cfg.queue_log_mode == "empty") {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_EMPTY, eventlist);
        qlf->set_sample_period(timeFromUs(cfg.queue_log_period_us));
    }

    // --- Build topology ----------------------------------------------------
    FatTreeTopology::set_tiers(cfg.no_of_tiers);
    if (cfg.custom_speeds)
        FatTreeTopology::set_downlink_speeds(cfg.host_nic_speed, cfg.fabric_speed, cfg.fabric_speed);

    Topology* topo_base = nullptr;
    FatTreeTopology* top_fat = nullptr;

    if (cfg.json_topo_file) {
        cout << "Loading JSON topology from " << cfg.json_topo_file << endl;
        JsonTopology* jt = new JsonTopology(&logfile, &eventlist, qlf, cfg.qt, cfg.queuesize);
        if (!jt->load(cfg.json_topo_file)) {
            cerr << "Failed to load JSON topology; exiting" << endl;
            return 1;
        }
        topo_base = jt;
    } else {
        top_fat = new FatTreeTopology(
            cfg.no_of_nodes,
            cfg.custom_speeds ? (linkspeed_bps)0 : cfg.fabric_speed,
            cfg.queuesize, qlf, &eventlist, NULL,
            cfg.qt, cfg.hop_latency, cfg.switch_latency, cfg.sender_qt);
        topo_base = top_fat;
    }

    int no_of_nodes = topo_base->no_of_nodes();
    cout << "Nodes: " << no_of_nodes << endl;

    // --- Queue name preamble (fat-tree only) --------------------------------
    if (top_fat) {
        auto write_names = [&](vector<vector<vector<BaseQueue*>>>& q3) {
            for (auto& tier : q3)
                for (auto& sw : tier)
                    for (auto* q : sw)
                        if (q) logfile.writeName(*q);
        };
        write_names(top_fat->queues_nlp_ns);
        write_names(top_fat->queues_ns_nlp);
        write_names(top_fat->queues_nlp_nup);
        write_names(top_fat->queues_nup_nlp);
        write_names(top_fat->queues_nup_nc);
        write_names(top_fat->queues_nc_nup);
    }

    // --- Handle list/print-and-exit modes ----------------------------------
    if (g_list_paths || g_list_kshort || g_list_kshort_names || g_list_hosts)
        return handle_list_modes(topo_base, no_of_nodes);

    // --- Load traffic matrix -----------------------------------------------
    ConnectionMatrix* conns = new ConnectionMatrix(no_of_nodes);
    if (!cfg.traffic_file.empty()) {
        cout << "Loading traffic matrix from " << cfg.traffic_file << endl;
        if (!conns->load(cfg.traffic_file.c_str())) {
            cerr << "Failed to load traffic matrix " << cfg.traffic_file << endl;
            exit(-1);
        }
    } else {
        cout << "No traffic matrix specified, using permutation" << endl;
        conns->setPermutation(no_of_nodes / 2);
    }

    if ((int)conns->N != no_of_nodes) {
        cerr << "TM node count (" << conns->N << ") != topology ("
             << no_of_nodes << ")" << endl;
        exit(-1);
    }

    // Apply link failures from TM.
    for (auto* f : conns->failures) {
        cout << "Link failure: type=" << f->switch_type
             << " switch=" << f->switch_id << " link=" << f->link_id << endl;
        if (top_fat) top_fat->add_failed_link(f->switch_type, f->switch_id, f->link_id);
    }

    // --- Path cache --------------------------------------------------------
    vector<const Route*>** path_cache = new vector<const Route*>*[no_of_nodes * no_of_nodes]();

    // --- Create flows ------------------------------------------------------
    vector<FlowInfo> flows;
    uint32_t flow_id = 0;

    vector<connection*>* all_conns = conns->getAllConnections();

    if (all_conns && !all_conns->empty()) {
        cout << "Creating " << all_conns->size() << " flows from connection objects" << endl;
        for (auto* crt : *all_conns) {
            flow_id++;
            FlowInfo fi = create_flow(crt, flow_id, topo_base, path_cache,
                                      eventlist, logfile, sink_logger,
                                      cfg.default_cbr_rate, cfg.use_multipath,
                                      cfg.route_strategy);
            if (fi.src) flows.push_back(fi);
        }
    } else {
        // Legacy map-based connections (no per-flow attributes).
        cout << "Using simple connection map" << endl;
        for (auto it = conns->connections.begin(); it != conns->connections.end(); it++) {
            uint32_t src = it->first;
            for (uint32_t dest : *it->second) {
                flow_id++;

                // Build a minimal connection struct for create_flow().
                connection c;
                c.src = src; c.dst = dest;
                c.size = 0; c.flowid = 0;
                c.start = timeFromMs(0);
                c.paths = 0; c.demand = 0; c.admitted = 0; c.rate_mbps = 0;
                c.send_done_trigger = 0; c.recv_done_trigger = 0;
                c.trigger = 0; c.priority = 2000000;

                FlowInfo fi = create_flow(&c, flow_id, topo_base, path_cache,
                                          eventlist, logfile, sink_logger,
                                          cfg.default_cbr_rate, cfg.use_multipath,
                                          cfg.route_strategy);
                if (fi.src) flows.push_back(fi);
            }
        }
    }

    cout << "Total flows: " << flow_id << endl;

    // --- Log simulation parameters -----------------------------------------
    logfile.write("# pktsize=" + to_string(Packet::data_packet_size()) + " bytes");
    logfile.write("# nodes=" + to_string(no_of_nodes));
    logfile.write("# fabricrate=" + to_string(cfg.fabric_speed / 1000000) + " Mbps");
    logfile.write("# hostnicrate=" + to_string(cfg.host_nic_speed / 1000000) + " Mbps");
    logfile.write("# default_rate=" + to_string(cfg.default_cbr_rate / 1000000) + " Mbps");
    logfile.write("# flows=" + to_string(flow_id));

    // --- Run simulation ----------------------------------------------------
    cout << "Starting simulation..." << endl;
    while (eventlist.doNextEvent()) {}
    cout << "Simulation complete!" << endl;

    // --- Post-simulation telemetry -----------------------------------------
    print_telemetry(flows);

    delete[] path_cache;
    return 0;
}
