// -*- c-basic-offset: 4; indent-tabs-mode: nil -*- 
#ifndef CBR_H
#define CBR_H

/*
 * A non responsive flow, source and sink
 */

#include <list>
#include <vector>
#include "config.h"
#include "network.h"
#include "eventlist.h"

class CbrSink;

class CbrSrc: public EventSource {
public:
    CbrSrc(EventList &eventlist,linkspeed_bps rate,simtime_picosec active=0,simtime_picosec idle=0);

    void connect(route_t& routeout, CbrSink& sink, simtime_picosec startTime);
    
    // Multi-path support with split ratios (probabilistic)
    void connect_multipath(vector<route_t*>& routes, const vector<double>& split_ratios, CbrSink& sink, simtime_picosec startTime);
    
    // Multi-path support with byte thresholds (deterministic switching)
    // thresholds[i] = switch to path i+1 after sending this many bytes
    // Example: thresholds = {1000, 5000} with 3 paths means:
    //   - path 0 for bytes 0-999
    //   - path 1 for bytes 1000-4999
    //   - path 2 for bytes 5000+
    void connect_multipath_thresholds(vector<route_t*>& routes, const vector<uint64_t>& thresholds, CbrSink& sink, simtime_picosec startTime);
    
    void send_packet();
    void doNextEvent();
    // Optional: limit total bytes to send for this CBR flow (0 = unlimited)
    void set_flow_size_bytes(uint64_t bytes) { _bytes_left = bytes; _flow_size_total = bytes; _done = (bytes==0); }
    uint64_t bytes_emitted() const { return _bytes_emitted; }
 
    // should really be private, but loggers want to see:
    linkspeed_bps _bitrate;
    int _crt_id;  
    int _mss;
    simtime_picosec _period,_active_time,_idle_time,_start_active,_end_active;
    bool _is_active;

private:
    // Connectivity
    PacketFlow _flow;
    CbrSink* _sink;
    route_t* _route;  // Single route (for backward compatibility)
    
    // Multi-path support
    vector<route_t*> _routes;  // Multiple routes
    vector<double> _split_ratios;  // Split ratios (should sum to 1.0)
    vector<double> _cumulative_ratios;  // Cumulative ratios for weighted selection
    bool _use_multipath;
    
    // Threshold-based path switching
    bool _use_thresholds;  // true = use byte thresholds, false = use split ratios
    vector<uint64_t> _byte_thresholds;  // Switch to path i+1 after _byte_thresholds[i] bytes
    
    // total bytes remaining to send (0 == unlimited)
    uint64_t _bytes_left;          // remaining bytes
    uint64_t _flow_size_total{0};  // original requested size (for diagnostics)
    uint64_t _bytes_emitted{0};    // total bytes emitted by this source
    bool _done{false};             // true when flow size exhausted
    // Mechanism
    void send_packets();
    route_t* select_route();  // Select route based on split ratios or thresholds
};

class CbrSink : public PacketSink, public DataReceiver {
    friend class CbrSrc;
public:
    CbrSink();
    ~CbrSink(){};
    void receivePacket(Packet& pkt);
    uint32_t _last_id; // the id of the last packet we have received
    uint32_t _received;//number of packets received;_last_id-_received = dropped packets 
    uint64_t _cumulative_ack;//_received * 1000 - this is for loggers

    uint64_t cumulative_ack(){return _cumulative_ack;}
    uint32_t drops(){return 1;}

    const string& nodename(){return _nodename;};
private:
    string _nodename;
    // Connectivity
};

#endif
