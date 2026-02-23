# HTSIM CBR Network Metrics Reference

This document explains every metric reported by `htsim_cbr` in its
post-simulation telemetry, how they relate to each other, and what they
mean in a traffic-engineering context.

---

## Telemetry Levels

Metrics are reported at three granularities, printed to stdout after the
simulation completes:

| Level | Prefix | Scope |
|-------|--------|-------|
| Per-flow | `FLOW_STATS` | One line per CBR flow |
| Per-pair | `PAIR_STATS` | One line per (src, dst) host pair (aggregated across flows) |
| Global | `GLOBAL_STATS` | Single line for the entire simulation |

---

## Metric Definitions

### Core Byte Counters

| Metric | Unit | Description |
|--------|------|-------------|
| `demand_bytes` (d_st) | bytes | Total application-layer demand. This is what the application *wants* to transfer. **Metadata only** — does not affect the simulation. Set via the `demand` token in the TM file. |
| `admitted_bytes` (b_st) | bytes | Traffic volume the TE solver decided to actually inject into the network. **This is the active flow size** — the CBR source stops sending after this many bytes. Set via the `admitted` token in the TM file. If `admitted` is not set, falls back to `size`. |
| `sent_bytes` | bytes | Total bytes the CBR source actually emitted into the network. Should equal `admitted_bytes` if the simulation ran long enough for the flow to complete. |
| `delivered_bytes` | bytes | Total bytes that arrived at the destination sink. Always ≤ `sent_bytes`. The difference is packets lost to queue overflows in the network. |
| `lost_bytes` | bytes | `sent_bytes − delivered_bytes`. Bytes that were injected into the network but never reached the destination (dropped at congested queues). |

### Derived Ratios

| Metric | Formula | Range | Meaning |
|--------|---------|-------|---------|
| `delivery_ratio` | `delivered_bytes / admitted_bytes` | 0.0 – 1.0 | How much of the solver's admitted volume was successfully delivered. **1.0 = the solver's admission was fully achievable.** < 1.0 = the solver over-admitted (promised more than the network could carry). |
| `loss_ratio` | `lost_bytes / sent_bytes` | 0.0 – 1.0 | Fraction of injected traffic that was dropped in the network. **0.0 = no loss.** Higher values indicate congestion. |

---

## Two Layers of "Loss"

In a TE workflow there are two distinct places where traffic can be reduced:

```
Application demand (d_st)
    │
    ├─ Solver rejection: d_st − b_st
    │   Traffic the solver chose NOT to send.
    │   Not visible to the network at all.
    │
    ▼
Admitted into network (b_st)
    │
    ├─ Network loss: sent_bytes − delivered_bytes
    │   Packets the solver DID send but the network dropped
    │   (queue overflow due to congestion).
    │
    ▼
Delivered to destination (delivered_bytes)
```

### Example

```
demand = 1,000,000,000 bytes  (1 GB — what the app wants)
admitted =  500,000,000 bytes  (500 MB — what the solver sends)
sent =      500,000,000 bytes  (500 MB — CBR source emitted all admitted)
delivered = 312,000,000 bytes  (312 MB — what actually arrived)
lost =      188,000,000 bytes  (188 MB — dropped in network)

Solver rejection:  1 GB − 500 MB = 500 MB  (not the network's problem)
Network loss:      500 MB − 312 MB = 188 MB
delivery_ratio:    312 MB / 500 MB = 0.624  (solver over-admitted)
loss_ratio:        188 MB / 500 MB = 0.376  (37.6% of injected traffic lost)
```

---

## What Each Ratio Tells You

### delivery_ratio (delivered / admitted)

This is the **solver validation metric**. It answers:

> "Did the network successfully deliver what the TE solver promised?"

| Value | Interpretation |
|-------|---------------|
| 1.0 | Solver admission was correct — the network carried everything it was asked to. |
| < 1.0 | Solver over-admitted — it allowed more traffic than the network could handle at the configured rates. Either reduce admitted volumes, lower sending rates, or spread traffic across more paths. |
| > 1.0 | Should not happen (delivered can't exceed admitted). If it does, check for a bug. |

### loss_ratio (lost / sent)

This is the **network congestion metric**. It answers:

> "How much of the traffic that entered the network was dropped?"

| Value | Interpretation |
|-------|---------------|
| 0.0 | No congestion — all packets delivered. |
| 0.01–0.05 | Mild congestion — a few packets dropped at bottleneck queues. |
| 0.05–0.20 | Moderate congestion — significant packet loss. |
| > 0.20 | Severe congestion — the link is heavily oversubscribed. |

Note: CBR is UDP-like (no congestion control), so it will keep sending at the
configured rate even when queues are overflowing — loss can be very high.

---

## Global-Level Metrics

The `GLOBAL_STATS` line aggregates across all flows:

| Metric | Formula |
|--------|---------|
| `total_demand_bytes` | Σ demand_bytes across all flows |
| `total_admitted_bytes` | Σ admitted_bytes across all flows |
| `total_sent_bytes` | Σ sent_bytes across all flows |
| `total_delivered_bytes` | Σ delivered_bytes across all flows |
| `total_lost_bytes` | `total_sent_bytes − total_delivered_bytes` |
| `global_delivery_ratio` | `total_delivered_bytes / total_admitted_bytes` |
| `global_loss_ratio` | `total_lost_bytes / total_sent_bytes` |

---

## Relationship to TM File Tokens

| TM Token | Maps to Metric | Notes |
|----------|---------------|-------|
| `demand <bytes>` | `demand_bytes` | Metadata only. Does not limit sending. |
| `admitted <bytes>` | `admitted_bytes` | Active flow size. Overrides `size`. CBR stops after this many bytes. |
| `size <bytes>` | `admitted_bytes` (fallback) | Used only if `admitted` is not set. |
| `rate <Mbps>` | — | Controls sending speed, not volume. Affects *when* loss happens, not *how much* is admitted. |

---

## Parsing Telemetry Programmatically

All metrics are printed as `key=value` pairs, easy to grep/awk:

```bash
# Extract per-flow loss ratios
./htsim_cbr ... 2>&1 | grep FLOW_STATS | awk -F'loss_ratio=' '{print $2}' | awk '{print $1}'

# Get global delivery ratio
./htsim_cbr ... 2>&1 | grep GLOBAL_STATS | grep -oP 'global_delivery_ratio=\K[0-9.]+'

# Get all lost bytes per pair
./htsim_cbr ... 2>&1 | grep PAIR_STATS | grep -oP 'src=\K\d+ dst=\d+ .* lost_bytes=\d+'

# Simple CSV extraction
./htsim_cbr ... 2>&1 | grep FLOW_STATS | sed 's/ /\n/g' | grep = | sed 's/.*=//' | paste -d, - - - - - - - - - - -
```
