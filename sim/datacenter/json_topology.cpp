// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "json_topology.h"
#include "main.h"
#include <iostream>
#include <algorithm>
#include <functional>
#include <queue>
#include <unordered_set>

JsonTopology::JsonTopology(Logfile* log, EventList* ev, QueueLoggerFactory* qlf, queue_type qt, mem_b queuesize) 
    : _logfile(log), _eventlist(ev), _qlf(qlf), _qt(qt), _queuesize(queuesize) {}

std::string JsonTopology::read_file(const char* filename) {
    std::ifstream in(filename, std::ios::in|std::ios::binary);
    if (!in) return "";
    std::ostringstream ss; ss << in.rdbuf();
    return ss.str();
}

std::string JsonTopology::trim(const std::string& s){
    size_t a=0; while(a<s.size() && isspace((unsigned char)s[a])) a++;
    size_t b=s.size(); while(b> a && isspace((unsigned char)s[b-1])) b--;
    return s.substr(a,b-a);
}

void JsonTopology::skip_ws(const std::string& s, size_t& pos){ while(pos<s.size() && isspace((unsigned char)s[pos])) pos++; }

bool JsonTopology::match_token(const std::string& s, size_t& pos, const std::string& token){
    skip_ws(s,pos);
    if (s.compare(pos, token.size(), token)==0){ pos += token.size(); return true; }
    return false;
}

bool JsonTopology::read_string(const std::string& s, size_t& pos, std::string& out){
    skip_ws(s,pos);
    if (pos>=s.size() || s[pos] != '"') return false;
    pos++; size_t start = pos;
    while (pos < s.size() && s[pos] != '"') pos++;
    if (pos>=s.size()) return false;
    out = s.substr(start, pos-start);
    pos++; return true;
}

bool JsonTopology::read_number(const std::string& s, size_t& pos, double& out){
    skip_ws(s,pos);
    size_t start = pos; bool dot=false; bool neg=false;
    if (pos < s.size() && (s[pos]=='-'||s[pos]=='+')) { neg=true; pos++; }
    while (pos < s.size() && (isdigit((unsigned char)s[pos]) || s[pos]=='.')) { if(s[pos]=='.') dot=true; pos++; }
    if (start==pos) return false;
    out = atof(s.substr(start,pos-start).c_str());
    return true;
}

bool JsonTopology::extract_object_block(const std::string& text, const std::string& key, std::string& out_array){
    // find "key" followed by ':' then either '[' for array block
    std::string pattern = '"'+key+'"';
    size_t p = text.find(pattern);
    if (p==std::string::npos) return false;
    p = text.find('[', p);
    if (p==std::string::npos) return false;
    int depth=0; size_t start=p; size_t i=p;
    for (; i<text.size(); i++){
        if (text[i]=='[') depth++;
        else if (text[i]==']'){ depth--; if(depth==0){ i++; break; } }
    }
    if (depth!=0) return false;
    out_array = text.substr(start, i-start);
    return true;
}

bool JsonTopology::parse_hosts(const std::string& text){
    std::string arr; if(!extract_object_block(text, "hosts", arr)){ std::cerr << "JsonTopology: missing hosts array" << std::endl; return false; }
    size_t pos=0; if(!match_token(arr,pos,"[")) return false;
    while(true){
        std::string h; if(!read_string(arr,pos,h)) break; // no more hosts
        if (_hostIndex.count(h)){ std::cerr << "Duplicate host id "<<h<<std::endl; return false; }
        int idx = _hosts.size(); _hosts.push_back(h); _hostIndex[h]=idx; // adjacency will be sized later
        skip_ws(arr,pos); if(arr[pos]==','){ pos++; continue; }
    }
    return true;
}

linkspeed_bps JsonTopology::interpret_speed(double val, const std::string& field){
    if (field=="speed_mbps") return speedFromMbps(val);
    if (field=="speed_gbps") return speedFromGbps(val);
    // fallback assume mbps
    return speedFromMbps(val);
}

simtime_picosec JsonTopology::interpret_latency(double val, const std::string& field){
    if (field=="latency_us") return timeFromUs(val);
    if (field=="latency_ms") return timeFromMs(val);
    if (field=="latency_ns") return timeFromNs((uint32_t)val);
    if (field=="latency_ps") return (simtime_picosec)val;
    return timeFromUs(val);
}

BaseQueue* JsonTopology::alloc_queue(QueueLogger* queueLogger, linkspeed_bps speed, mem_b queuesize) {
    switch (_qt) {
    case RANDOM:
        return new RandomQueue(speed, queuesize, *_eventlist, queueLogger, memFromPkt(RANDOM_BUFFER));
    case COMPOSITE:
        return new CompositeQueue(speed, queuesize, *_eventlist, queueLogger);
    case ECN:
        return new ECNQueue(speed, queuesize, *_eventlist, queueLogger, memFromPkt(15));
    case ECN_PRIO:
        return new ECNPrioQueue(speed, queuesize, queuesize,
                                queuesize * 0.2,  // ECN threshold at 20%
                                queuesize * 0.2,
                                *_eventlist, queueLogger);
    case LOSSLESS:
        return new LosslessQueue(speed, queuesize, *_eventlist, queueLogger, NULL);
    case LOSSLESS_INPUT:
        return new LosslessOutputQueue(speed, queuesize, *_eventlist, queueLogger);
    case LOSSLESS_INPUT_ECN:
        return new LosslessOutputQueue(speed, memFromPkt(10000), *_eventlist, queueLogger, 1, memFromPkt(16));
    case COMPOSITE_ECN:
        return new ECNQueue(speed, queuesize, *_eventlist, queueLogger, memFromPkt(15));
    case PRIORITY:
        return new PriorityQueue(speed, queuesize, *_eventlist, queueLogger);
    default:
        // Default to basic Queue for unsupported types
        return new Queue(speed, queuesize, *_eventlist, queueLogger);
    }
}

bool JsonTopology::parse_links(const std::string& text){
    std::string arr; if(!extract_object_block(text, "links", arr)){ std::cerr << "JsonTopology: missing links array" << std::endl; return false; }
    _adj.resize(_hosts.size());
    size_t pos=0; if(!match_token(arr,pos,"[")) return false;
    while(true){
        skip_ws(arr,pos);
        if (pos>=arr.size() || arr[pos]==']') break;
        if (arr[pos] != '{'){ std::cerr << "Expected link object"<<std::endl; return false; }
        pos++; // inside object
        std::string src="", dst=""; double speedVal=0; std::string speedField=""; double latVal=0; std::string latField="";
        // Optional direction/asymmetry
        bool bidirectional = true;
        double revSpeedVal=0; std::string revSpeedField=""; double revLatVal=0; std::string revLatField="";
        while(true){
            std::string key; if(!read_string(arr,pos,key)){ std::cerr << "Bad key in link object"<<std::endl; return false; }
            if(!match_token(arr,pos,":")){ std::cerr << "Missing ':' after key"<<std::endl; return false; }
            if (key=="src"||key=="dst"){
                std::string v; if(!read_string(arr,pos,v)){ std::cerr << "Bad string value for "<<key<<std::endl; return false; }
                if (key=="src") src=v; else dst=v;
            } else if (key.rfind("speed_",0)==0){ double v; if(!read_number(arr,pos,v)){ std::cerr << "Bad number for speed field"<<std::endl; return false; } speedVal=v; speedField=key; }
            else if (key.rfind("latency_",0)==0){ double v; if(!read_number(arr,pos,v)){ std::cerr << "Bad number for latency field"<<std::endl; return false; } latVal=v; latField=key; }
            else if (key=="bidirectional"){
                // accept true/false literals
                skip_ws(arr,pos);
                if (arr.compare(pos,4,"true")==0){ bidirectional=true; pos+=4; }
                else if (arr.compare(pos,5,"false")==0){ bidirectional=false; pos+=5; }
                else { std::cerr<<"Bad boolean for bidirectional"<<std::endl; return false; }
            }
            else if (key.rfind("rev_speed_",0)==0){ double v; if(!read_number(arr,pos,v)){ std::cerr << "Bad number for rev_speed field"<<std::endl; return false; } revSpeedVal=v; revSpeedField=key.substr(4); /* drop 'rev_' prefix -> speed_* */ }
            else if (key.rfind("rev_latency_",0)==0){ double v; if(!read_number(arr,pos,v)){ std::cerr << "Bad number for rev_latency field"<<std::endl; return false; } revLatVal=v; revLatField=key.substr(4); /* drop 'rev_' prefix -> latency_* */ }
            else { // skip unknown token (string/number)
                std::string maybeStr; double maybeNum; if(read_string(arr,pos,maybeStr)) { /*ignored*/ } else if(read_number(arr,pos,maybeNum)) { /*ignored*/ } else { std::cerr<<"Unsupported value in link"<<std::endl; return false; }
            }
            skip_ws(arr,pos);
            if (arr[pos]==','){ pos++; continue; }
            if (arr[pos]=='}'){ pos++; break; }
        }
        if (src==""||dst=="") { std::cerr << "Link missing src/dst"<<std::endl; return false; }
        if (!_hostIndex.count(src) || !_hostIndex.count(dst)){ std::cerr<<"Unknown host id in link: "<<src<<" or "<<dst<<std::endl; return false; }
        linkspeed_bps spd = interpret_speed(speedVal, speedField);
        simtime_picosec lat = interpret_latency(latVal, latField);
        int sidx=_hostIndex[src]; int didx=_hostIndex[dst];
        // create forward edge components
        QueueLogger* qlogger_f = _qlf ? _qlf->createQueueLogger() : NULL;
        BaseQueue* qf = alloc_queue(qlogger_f, spd, _queuesize);
        std::string qname_f = "q_"+src+"_"+dst; qf->forceName(qname_f); if(_logfile) _logfile->writeName(*qf);
        Pipe* pf = new Pipe(lat, *_eventlist); pf->forceName("p_"+src+"_"+dst); if(_logfile) _logfile->writeName(*pf);
        qf->setNext(pf); // queue feeds pipe
    _adj[sidx][didx].q = qf;
    _adj[sidx][didx].p = pf;
        // reverse direction (optional/asymmetric)
        if (bidirectional) {
            linkspeed_bps rspd = spd;
            simtime_picosec rlat = lat;
            if (!revSpeedField.empty()) rspd = interpret_speed(revSpeedVal, revSpeedField);
            if (!revLatField.empty()) rlat = interpret_latency(revLatVal, revLatField);

            QueueLogger* qlogger_r = _qlf ? _qlf->createQueueLogger() : NULL;
            BaseQueue* qr = alloc_queue(qlogger_r, rspd, _queuesize);
            qr->forceName("q_"+dst+"_"+src); if(_logfile) _logfile->writeName(*qr);
            Pipe* pr = new Pipe(rlat, *_eventlist); pr->forceName("p_"+dst+"_"+src); if(_logfile) _logfile->writeName(*pr);
            qr->setNext(pr);
        _adj[didx][sidx].q = qr;
        _adj[didx][sidx].p = pr;
        }
        skip_ws(arr,pos);
        if (arr[pos]==','){ pos++; continue; }
    }
    return true;
}

bool JsonTopology::load(const char* filename){
    std::string content = read_file(filename);
    if (content.empty()){ std::cerr << "JsonTopology: failed to read file "<<filename<<std::endl; return false; }
    if(!parse_hosts(content)) return false;
    if(!parse_links(content)) return false;
    std::cout << "JsonTopology: loaded "<<_hosts.size()<<" hosts, " ;
    size_t linkCount = 0; for(auto &m : _adj) linkCount += m.size(); // directed
    std::cout << linkCount/2 << " undirected links" << std::endl;
    return true;
}

vector<uint32_t>* JsonTopology::get_neighbours(uint32_t src){
    if (src >= _adj.size()) return NULL;
    vector<uint32_t>* n = new vector<uint32_t>();
    for (auto &kv : _adj[src]) n->push_back(kv.first);
    return n;
}

vector<const Route*>* JsonTopology::get_bidir_paths(uint32_t src, uint32_t dest, bool reverse){
    vector<const Route*>* paths = new vector<const Route*>();
    if (src >= _hosts.size() || dest >= _hosts.size() || src==dest){ return paths; }
    // Enumerate ALL shortest paths via layered BFS predecessor sets.
    const size_t N = _hosts.size();
    std::vector<int> dist(N, -1);
    std::vector< std::vector<int> > preds(N); // predecessors on shortest paths
    std::vector<int> q; q.reserve(N);
    size_t head=0; q.push_back(src); dist[src]=0;
    while(head<q.size()){
        int u=q[head++];
        int nextd = dist[u]+1;
        for(auto &kv: _adj[u]){
            int v=kv.first;
            if(dist[v]==-1){ dist[v]=nextd; preds[v].push_back(u); q.push_back(v); }
            else if(dist[v]==nextd){ // another predecessor offering same shortest distance
                preds[v].push_back(u);
            }
        }
    }
    if(dist[dest]==-1){ return paths; } // disconnected
    int shortest_len = dist[dest];

    // Backtrack recursively to assemble all node sequences (src..dest)
    std::vector<std::vector<int>> sequences;
    std::vector<int> current;
    std::function<void(int)> dfs = [&](int node){
        current.push_back(node);
        if(node==(int)src){
            // we built in reverse order, copy reversed into sequence
            std::vector<int> seq(current.rbegin(), current.rend());
            sequences.push_back(seq);
        } else {
            for(int p: preds[node]) dfs(p);
        }
        current.pop_back();
    };
    dfs(dest);

    build_routes_from_sequences(sequences, paths);
    // Filter to only those paths with exact shortest length (in hops == shortest_len)
    vector<const Route*>* filtered = new vector<const Route*>();
    for (auto* r: *paths){
        if (r->size()/2 == (size_t)shortest_len) filtered->push_back(r);
        else delete r; // discard longer path (should not normally happen)
    }
    delete paths;
    paths = filtered;
    return paths;
}

// Return shortest path (by hops) from s to t, avoiding banned nodes/edges. Returns sequence of nodes or empty if none.
std::vector<int> JsonTopology::bfs_shortest_path(int s, int t,
                                       const std::vector<bool>& banned_nodes,
                                       const std::unordered_set<long long>& banned_edges) const {
    const size_t N = _hosts.size();
    std::vector<int> dist(N, -1), prev(N, -1);
    std::vector<int> q; q.reserve(N);
    if (s < 0 || t < 0 || s >= (int)N || t >= (int)N) return {};
    if (banned_nodes.size() == N && (banned_nodes[s] || banned_nodes[t])) return {};
    if (banned_nodes.size()!=0 && banned_nodes[s]) return {};
    dist[s]=0; q.push_back(s); size_t head=0;
    while(head<q.size()){
        int u=q[head++];
        if (u==t) break;
        if (banned_nodes.size()!=0 && banned_nodes[u]) continue;
        for (auto &kv: _adj[u]){
            int v=kv.first;
            if (banned_nodes.size()!=0 && banned_nodes[v]) continue;
            if (banned_edges.count(edge_key(u,v))) continue;
            if (dist[v]==-1){ dist[v]=dist[u]+1; prev[v]=u; q.push_back(v); }
        }
    }
    if (dist[t]==-1) return {};
    std::vector<int> path; int cur=t; while(cur!=-1){ path.push_back(cur); cur=prev[cur]; }
    std::reverse(path.begin(), path.end());
    return path;
}

vector<const Route*>* JsonTopology::get_k_shortest_paths(uint32_t src, uint32_t dest, size_t K){
    vector<const Route*>* out = new vector<const Route*>();
    if (src >= _hosts.size() || dest >= _hosts.size() || src==dest || K==0) return out;

    // Yen's algorithm (unweighted): generate up to K simple paths ordered by hop count
    // yen_paths is list of paths found; candidate_heap is min-heap of candidate spur paths with costs
    struct Cand { std::vector<int> path; int cost; };
    auto cmp = [](const Cand& a, const Cand& b){ return a.cost > b.cost; };
    std::priority_queue<Cand, std::vector<Cand>, decltype(cmp)> candidate_heap(cmp);

    // Initial shortest path
    std::vector<bool> empty_nodes; std::unordered_set<long long> empty_edges;
    std::vector<int> p0 = bfs_shortest_path((int)src, (int)dest, empty_nodes, empty_edges);
    if (p0.empty()) return out;
    std::vector<std::vector<int>> yen_paths; yen_paths.push_back(p0);

    // Helper lambda to check duplicate path
    auto path_equals = [](const std::vector<int>& a, const std::vector<int>& b){
        return a.size()==b.size() && std::equal(a.begin(), a.end(), b.begin());
    };

    for (size_t k = 1; k < K; ++k){
    const std::vector<int>& last = yen_paths.back();
        // For each node in last path (except last), compute spur path
        for (size_t i = 0; i + 1 < last.size(); ++i){
            int spurNode = last[i];
            std::vector<int> rootPath(last.begin(), last.begin() + i + 1);

            // Build banned sets
            std::unordered_set<long long> banned_edges;
            std::vector<bool> banned_nodes(_hosts.size(), false);
            // Ban nodes in rootPath except spurNode to prevent loops
            for (size_t r = 0; r + 1 < rootPath.size(); ++r){
                banned_nodes[rootPath[r]] = true;
            }
            // Ban edges that would replicate previous A paths sharing same root
            for (const auto& p : yen_paths){
                if (p.size() > i && std::equal(p.begin(), p.begin()+i+1, rootPath.begin())){
                    int u = p[i]; int v = p[i+1];
                    banned_edges.insert(edge_key(u,v));
                }
            }

            // Find spur path from spurNode to dest
            std::vector<int> spurPath = bfs_shortest_path(spurNode, (int)dest, banned_nodes, banned_edges);
            if (spurPath.empty()) continue;
            // Combine rootPath (without spurNode duplicate) + spurPath
            std::vector<int> total = rootPath;
            total.pop_back();
            total.insert(total.end(), spurPath.begin(), spurPath.end());

            // Deduplicate: skip if already in A or in B
            bool dup=false;
            for (const auto& p : yen_paths){ if (path_equals(p, total)) { dup=true; break; } }
            if (dup) continue;
            // Compute cost (hop count)
            int cost = (int)total.size()-1;
            candidate_heap.push(Cand{total, cost});
        }
        if (candidate_heap.empty()) break;
        // Pick lowest-cost candidate not yet in A
        Cand best = candidate_heap.top(); candidate_heap.pop();
        // There may be duplicates in heap; ensure uniqueness vs A
        while(true){
            bool dup=false; for (const auto& p : yen_paths){ if (path_equals(p, best.path)) { dup=true; break; } }
            if (!dup) break;
            if (candidate_heap.empty()) { best.path.clear(); break; }
            best = candidate_heap.top(); candidate_heap.pop();
        }
        if (best.path.empty()) break;
        yen_paths.push_back(best.path);
    }

    // Build Route objects for A
    build_routes_from_sequences(yen_paths, out);
    return out;
}

void JsonTopology::build_routes_from_sequences(const std::vector<std::vector<int>>& sequences,
                                               std::vector<const Route*>*& out_paths){
    for(const auto& seq: sequences){
        if(seq.size()<2) continue; // ignore trivial
        Route* r = new Route();
        for(size_t i=0;i+1<seq.size();i++){
            int a=seq[i]; int b=seq[i+1];
            auto itA = _adj[a].find(b);
            if(itA==_adj[a].end()) { r->push_back(nullptr); break; }
            DirEdge &edge = itA->second;
            r->push_back(edge.q); r->push_back(edge.p);
        }
        out_paths->push_back(r);
    }
}

Route* JsonTopology::build_route_from_queue_names(const std::vector<std::string>& queue_names) {
    // Parse queue names like "q_r1_r2" to extract source/dest host names
    // Format: q_<src_host>_<dst_host> where src_host/dst_host are strings like "r1", "r2"
    Route* r = new Route();
    
    for (const std::string& qname : queue_names) {
        // Parse: q_<src>_<dst>
        if (qname.size() < 6 || qname.substr(0, 2) != "q_") {
            std::cerr << "Invalid queue name format: " << qname << " (expected q_<src>_<dst>)" << std::endl;
            delete r;
            return nullptr;
        }
        
        // Find the second underscore (after "q_")
        size_t first_underscore = 1; // position of first '_' in "q_"
        size_t second_underscore = qname.find('_', first_underscore + 1);
        if (second_underscore == std::string::npos) {
            std::cerr << "Invalid queue name format: " << qname << " (missing second underscore)" << std::endl;
            delete r;
            return nullptr;
        }
        
        std::string src_host = qname.substr(first_underscore + 1, second_underscore - first_underscore - 1);
        std::string dst_host = qname.substr(second_underscore + 1);
        
        // Look up host indices
        auto src_it = _hostIndex.find(src_host);
        auto dst_it = _hostIndex.find(dst_host);
        if (src_it == _hostIndex.end() || dst_it == _hostIndex.end()) {
            std::cerr << "Unknown host in queue name: " << qname 
                      << " (src=" << src_host << ", dst=" << dst_host << ")" << std::endl;
            delete r;
            return nullptr;
        }
        
        int src_idx = src_it->second;
        int dst_idx = dst_it->second;
        
        // Look up edge in adjacency
        auto edge_it = _adj[src_idx].find(dst_idx);
        if (edge_it == _adj[src_idx].end()) {
            std::cerr << "No edge found for queue: " << qname << std::endl;
            delete r;
            return nullptr;
        }
        
        DirEdge& edge = edge_it->second;
        r->push_back(edge.q);
        r->push_back(edge.p);
    }
    
    return r;
}

