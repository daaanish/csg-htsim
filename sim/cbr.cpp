// -*- c-basic-offset: 4; indent-tabs-mode: nil -*- 
#include "cbr.h"
#include "math.h"
#include <iostream>
#include <vector>
#include "cbrpacket.h"
////////////////////////////////////////////////////////////////
//  CBR SOURCE
////////////////////////////////////////////////////////////////

CbrSrc::CbrSrc(EventList &eventlist,linkspeed_bps rate,simtime_picosec active,simtime_picosec idle)
    : EventSource(eventlist,"cbr"),  _bitrate(rate),_crt_id(1),_mss(1500),_flow(NULL)
{
    _period = (simtime_picosec)((pow(10.0,12.0) * 8 * _mss) / _bitrate);
    _sink = NULL;
    _route = NULL;
    _use_multipath = false;
    _use_thresholds = false;
    _start_active = 0;
    _end_active = 0;
    _idle_time = idle;
    _active_time = active;
    _is_active = false;
    _bytes_left = 0; // 0 => unlimited
    _flow_size_total = 0;
    _done = false;
    _bytes_emitted = 0;
}

void 
CbrSrc::connect(route_t& routeout, CbrSink& sink, simtime_picosec starttime) 
{
    _route = &routeout;
    _sink = &sink;
    _use_multipath = false;
    _use_thresholds = false;
    _flow.set_id(get_id()); // identify the packet flow with the CBR source that generated it
    _is_active = true;
    _start_active = starttime;
    _end_active = _start_active + (simtime_picosec)(2.0*drand()*_active_time);
    eventlist().sourceIsPending(*this,starttime);
}

void 
CbrSrc::connect_multipath(vector<route_t*>& routes, const vector<double>& split_ratios, CbrSink& sink, simtime_picosec starttime)
{
    assert(routes.size() == split_ratios.size());
    assert(routes.size() > 0);
    
    _routes = routes;
    _split_ratios = split_ratios;
    _sink = &sink;
    _use_multipath = true;
    _use_thresholds = false;
    _route = NULL;  // Not using single route
    
    // Normalize split ratios to ensure they sum to 1.0
    double sum = 0.0;
    for (size_t i = 0; i < split_ratios.size(); i++) {
        sum += split_ratios[i];
    }
    if (sum > 0.0) {
        for (size_t i = 0; i < split_ratios.size(); i++) {
            _split_ratios[i] /= sum;
        }
    } else {
        // If all zeros, distribute equally
        double equal = 1.0 / routes.size();
        for (size_t i = 0; i < routes.size(); i++) {
            _split_ratios[i] = equal;
        }
    }
    
    // Build cumulative ratios for weighted random selection
    _cumulative_ratios.clear();
    double cumsum = 0.0;
    for (size_t i = 0; i < _split_ratios.size(); i++) {
        cumsum += _split_ratios[i];
        _cumulative_ratios.push_back(cumsum);
    }
    
    _flow.set_id(get_id());
    _is_active = true;
    _start_active = starttime;
    _end_active = _start_active + (simtime_picosec)(2.0*drand()*_active_time);
    eventlist().sourceIsPending(*this,starttime);
}

void 
CbrSrc::connect_multipath_thresholds(vector<route_t*>& routes, const vector<uint64_t>& thresholds, CbrSink& sink, simtime_picosec starttime)
{
    // thresholds should have size = routes.size() - 1
    // thresholds[i] = byte count at which we switch from path i to path i+1
    assert(routes.size() > 0);
    assert(thresholds.size() == routes.size() - 1 || thresholds.size() == routes.size());
    
    _routes = routes;
    _byte_thresholds = thresholds;
    _sink = &sink;
    _use_multipath = true;
    _use_thresholds = true;
    _route = NULL;
    
    _flow.set_id(get_id());
    _is_active = true;
    _start_active = starttime;
    _end_active = _start_active + (simtime_picosec)(2.0*drand()*_active_time);
    eventlist().sourceIsPending(*this,starttime);
}

route_t*
CbrSrc::select_route() {
    if (!_use_multipath || _routes.size() == 0) {
        return _route;  // Fall back to single route
    }
    
    if (_routes.size() == 1) {
        return _routes[0];
    }
    
    // Threshold-based deterministic selection
    if (_use_thresholds) {
        // Find which path to use based on bytes already emitted
        for (size_t i = 0; i < _byte_thresholds.size(); i++) {
            if (_bytes_emitted < _byte_thresholds[i]) {
                return _routes[i];
            }
        }
        // Past all thresholds, use last path
        return _routes[_routes.size() - 1];
    }
    
    // Weighted random selection (probabilistic split)
    double r = drand();
    for (size_t i = 0; i < _cumulative_ratios.size(); i++) {
        if (r <= _cumulative_ratios[i]) {
            return _routes[i];
        }
    }
    
    // Fallback (shouldn't reach here)
    return _routes[_routes.size() - 1];
}

void 
CbrSrc::doNextEvent() {
    // Guard: if flow size exhausted, stop scheduling further sends
    if (_done && _flow_size_total>0) {
        return; // no more packets
    }
    if (_idle_time==0||_active_time==0){
        send_packet();
        return;
    }

    if (_is_active){
        if (eventlist().now()>=_end_active){
            _is_active = false;
            eventlist().sourceIsPendingRel(*this,(simtime_picosec)(2*drand()*_idle_time));
        }
        else
            send_packet();
    }
    else {
        _is_active = true;
        _start_active = eventlist().now();
        _end_active = _start_active + (simtime_picosec)(2.0*drand()*_active_time);
        send_packet();
    }
}

void 
CbrSrc::send_packet() {
    if (_done && _flow_size_total>0) return; // double guard
    route_t* selected_route = select_route();
    assert(selected_route != NULL);
    
    int pkt_size = _mss;
    if (_bytes_left > 0) {
        if ((uint64_t)pkt_size > _bytes_left) pkt_size = (int)_bytes_left;
    }
    Packet* p = CbrPacket::newpkt(_flow, *selected_route, _crt_id++, pkt_size);
    p->sendOn();
    _bytes_emitted += pkt_size;

    if (_bytes_left > 0) {
        if ((uint64_t)pkt_size >= _bytes_left) {
            // sent final bytes for this flow; stop scheduling further sends
            _bytes_left = 0;
            _done = true;
            // Optional debug output
            if (_flow_size_total>0) {
                cout << "CBR flow " << _flow.get_id() << " finished at t=" << timeAsSec(eventlist().now())
                     << "s total_bytes=" << _flow_size_total << endl;
            }
            return;
        } else {
            _bytes_left -= pkt_size;
        }
    }

    //  simtime_picosec how_long = _period;
    //simtime_picosec _active_already = eventlist().now()-_start_active;

    //if (_active_time!=0&&_idle_time!=0&&period>)

    // Schedule next send only if not done
    if (!_done)
        eventlist().sourceIsPendingRel(*this,_period);
}

////////////////////////////////////////////////////////////////
//  Cbr SINK
////////////////////////////////////////////////////////////////

CbrSink::CbrSink() 
    : DataReceiver("cbr")  {
    // _nodename will be overridden by main_cbr with a detailed name (cbr_sink_src_dest_flowid).
    // Provide a default for safety.
    _nodename = "cbr_sink";
    _received = 0;
    _last_id = 0;
    _cumulative_ack = 0;
}

// Note: _cumulative_ack is the last byte we've ACKed.
// seqno is the first byte of the new packet.
void
CbrSink::receivePacket(Packet& pkt) {
    _received++;
    _cumulative_ack += pkt.size();
    _last_id = pkt.id();
    pkt.free();
}        

