// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef JSON_TOPOLOGY_H
#define JSON_TOPOLOGY_H

#include "topology.h"
#include "queue.h"
#include "randomqueue.h"
#include "compositequeue.h"
#include "ecnqueue.h"
#include "ecnprioqueue.h"
#include "queue_lossless.h"
#include "queue_lossless_input.h"
#include "queue_lossless_output.h"
#include "prioqueue.h"
#include "pipe.h"
#include "logfile.h"
#include "eventlist.h"
#include "loggers.h"
#include <string>
#include <vector>
#include <unordered_map>
#include <fstream>
#include <sstream>
#include <cctype>
#include <unordered_set>
#include <queue>

#ifndef QT
#define QT
typedef enum {UNDEFINED, RANDOM, ECN, COMPOSITE, PRIORITY,
              CTRL_PRIO, FAIR_PRIO, LOSSLESS, LOSSLESS_INPUT, LOSSLESS_INPUT_ECN,
              COMPOSITE_ECN, COMPOSITE_ECN_LB, SWIFT_SCHEDULER, ECN_PRIO, AEOLUS, AEOLUS_ECN} queue_type;
#endif

// A very lightweight JSON-driven topology for ad-hoc / random graphs.
// Intended format (minimal subset of JSON accepted – whitespace optional):
// {
//   "hosts": ["h0", "h1", "h2"],
//   "links": [
//      {"src":"h0", "dst":"h1", "speed_mbps":1000, "latency_us":1},
//      {"src":"h1", "dst":"h2", "speed_gbps":10, "latency_us":1},
//      {"src":"h0", "dst":"h2", "speed_gbps":10, "latency_us":2}
//   ]
// }
//
// Each link is treated as bidirectional by default; per direction we
// instantiate a Queue and a Pipe (queue->pipe). 

class JsonTopology : public Topology {
public:
    JsonTopology(Logfile* log, EventList* ev, QueueLoggerFactory* qlf = nullptr, 
                 queue_type qt = COMPOSITE, mem_b queuesize = memFromPkt(100));
    bool load(const char* filename);
    
    // Expose host names (zero-based order) for convenience in CLI tools
    const std::vector<std::string>& get_hosts() const { return _hosts; }
    virtual vector<const Route*>* get_bidir_paths(uint32_t src, uint32_t dest, bool reverse);
    // Return up to K shortest simple paths by hop-count between src and dest (JSON topology only)
    vector<const Route*>* get_k_shortest_paths(uint32_t src, uint32_t dest, size_t K);
    virtual vector<uint32_t>* get_neighbours(uint32_t src);
    virtual uint32_t no_of_nodes() const { return _hosts.size(); }
    virtual void add_switch_loggers(Logfile& log, simtime_picosec sample_period) { /* no switches */ }
    
    // Build a Route from explicit queue names (e.g., "q_r1_r2", "q_r2_r5")
    // Queue name format: q_r<src>_r<dst> where src/dst are 1-indexed router numbers
    Route* build_route_from_queue_names(const std::vector<std::string>& queue_names);

private:
    BaseQueue* alloc_queue(QueueLogger* queueLogger, linkspeed_bps speed, mem_b queuesize);
    struct DirEdge { // directed edge components
        BaseQueue* q{nullptr};
        Pipe* p{nullptr};
    };
    Logfile* _logfile;
    EventList* _eventlist;
    QueueLoggerFactory* _qlf{nullptr};
    queue_type _qt;
    mem_b _queuesize;
    std::vector<std::string> _hosts;               // host ID strings
    std::unordered_map<std::string,int> _hostIndex;// mapping ID -> index
    // adjacency[src][dst] = DirEdge
    std::vector< std::unordered_map<int, DirEdge> > _adj;

    // Build Route objects from a list of node-index sequences
    void build_routes_from_sequences(const std::vector<std::vector<int>>& sequences,
                                     std::vector<const Route*>*& out_paths);

    // Helpers for K-shortest (unweighted) path search
    std::vector<int> bfs_shortest_path(int s, int t,
                                       const std::vector<bool>& banned_nodes,
                                       const std::unordered_set<long long>& banned_edges) const;
    static long long edge_key(int u, int v) { return ((long long)u<<32) | (unsigned long long)(unsigned int)v; }

    // Parsing helpers (very small, NOT a general JSON parser)
    static std::string read_file(const char* filename);
    bool parse_hosts(const std::string& text);
    bool parse_links(const std::string& text);
    bool extract_object_block(const std::string& text, const std::string& key, std::string& out_array);
    static std::string trim(const std::string& s);
    static bool match_token(const std::string& s, size_t& pos, const std::string& token);
    static bool read_string(const std::string& s, size_t& pos, std::string& out);
    static bool read_number(const std::string& s, size_t& pos, double& out);
    static void skip_ws(const std::string& s, size_t& pos);
    linkspeed_bps interpret_speed(double val, const std::string& field_name);
    simtime_picosec interpret_latency(double val, const std::string& field_name);
};

#endif
