#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd=None, capture=True):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT, text=True, check=False)
    return p.returncode, (p.stdout or "")


def ensure_binaries(datacenter_dir: Path):
    htsim = datacenter_dir / "htsim_cbr"
    parse_output = datacenter_dir.parent / "parse_output"
    rebuilt = False
    if not htsim.exists():
        print("Building htsim_cbr...")
        rc, out = run(["make", "htsim_cbr"], cwd=str(datacenter_dir))
        if rc != 0:
            print(out)
            sys.exit(1)
        rebuilt = True
    if not parse_output.exists():
        print("Building parse_output...")
        rc, out = run(["make", "parse_output"], cwd=str(datacenter_dir.parent))
        if rc != 0:
            print(out)
            sys.exit(1)
        rebuilt = True
    return rebuilt


def list_hosts(datacenter_dir: Path, topo: str):
    cmd = ["./htsim_cbr", "-json_topo", topo, "-list_hosts"]
    rc, out = run(cmd, cwd=str(datacenter_dir))
    if rc != 0:
        print(out)
        sys.exit(1)
    hosts = []
    capture = False
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Host indices (zero-based):"):
            capture = True
            continue
        if capture and line and ":" in line:
            # Format: "0: hostname"
            idx, name = line.split(":", 1)
            hosts.append((int(idx.strip()), name.strip()))
    if not hosts:
        # Fallback: ask the binary for nodes during a null run? But better to enforce JSON topology listing.
        raise RuntimeError("Failed to list hosts from topology. Ensure it's a JSON topology.")
    return hosts


def write_tm(tm_path: Path, nodes: int, flows: list):
    with tm_path.open("w") as f:
        f.write(f"Nodes {nodes}\n")
        f.write(f"Connections {len(flows)}\n\n")
        for fl in flows:
            src = int(fl["src"]) if isinstance(fl["src"], (int, str)) else fl["src"]
            dst = int(fl["dst"]) if isinstance(fl["dst"], (int, str)) else fl["dst"]
            size = int(fl.get("size", 0))
            paths = fl.get("paths", [])
            weights = fl.get("weights", [])
            # Allow explicit per-flow start time via start_sec (seconds); default 0
            start_sec = float(fl.get("start_sec", 0.0))
            # TM syntax expects integer or float seconds after 'start'
            parts = [f"{src}->{dst}", "start", "0", "size", str(size)]
            if start_sec != 0.0:
                # Replace the start time token (index 2)
                parts[2] = ("{:.6f}".format(start_sec).rstrip("0").rstrip(".") if start_sec % 1 != 0 else str(int(start_sec)))
            if paths:
                if len(paths) > 1:
                    parts += ["paths", str(len(paths))]
                parts += ["paths_idx", ",".join(str(int(p)) for p in paths)]
            if weights:
                parts += ["split", ",".join(str(float(w)) for w in weights)]
            f.write(" ".join(parts) + "\n")


def parse_flow_stats(stdout_text: str):
    # FLOW_STATS flow=1 src=1 dst=10 sent_bytes=50000000 received_bytes=50000000
    stats = {}
    pat = re.compile(r"^FLOW_STATS\s+flow=(\d+)\s+src=(\d+)\s+dst=(\d+)\s+sent_bytes=(\d+)\s+received_bytes=(\d+)")
    for line in stdout_text.splitlines():
        m = pat.match(line.strip())
        if m:
            flow_id = int(m.group(1))
            src = int(m.group(2))
            dst = int(m.group(3))
            sent = int(m.group(4))
            rcvd = int(m.group(5))
            stats[(src, dst, flow_id)] = {"src": src, "dst": dst, "flow_id": flow_id, "bytes_sent": sent, "bytes_received": rcvd}
    return stats


def parse_throughputs(datacenter_dir: Path, log_path: Path):
    # parse_output -cbr -show lines: "<Mbps> Mbps val <id> name cbr_sink_src_dst_flowid"
    rc, out = run([str(datacenter_dir.parent / "parse_output"), str(log_path), "-cbr", "-show"], cwd=str(datacenter_dir))
    tputs = {}
    if rc != 0:
        print(out)
        return tputs
    pat = re.compile(r"^(?P<mbps>[0-9.]+)\s+Mbps.*name\s+cbr_sink_(?P<src>\d+)_(?P<dst>\d+)_(?P<flow>\d+)")
    for line in out.splitlines():
        m = pat.match(line.strip())
        if m:
            src = int(m.group("src"))
            dst = int(m.group("dst"))
            flow_id = int(m.group("flow"))
            mbps = float(m.group("mbps"))
            tputs[(src, dst, flow_id)] = mbps
    return tputs


def parse_tm_file(tm_path: Path):
    """Parse a .tm file to extract per-flow declared paths and split weights.

    Returns a list of dicts: {src:int, dst:int, paths:[int], weights:[float]}
    Notes:
    - Only parses simple single-line flow declarations like:
      "1->10 start 0 size 50000000 paths 2 paths_idx 0,1 split 0.5,0.5"
    - Comments and blank lines are ignored.
    - If no split is present, weights will be [].
    - If no paths_idx is present, paths will be [].
    """
    flows = []
    if not tm_path.exists():
        return flows
    line_re = re.compile(r"^\s*(\d+)->(\d+)\b(.*)$")
    paths_re = re.compile(r"\b(paths_idx|path_indices)\s+([0-9,]+)")
    split_re = re.compile(r"\bsplit\s+([0-9.,]+)")
    with tm_path.open() as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = line_re.match(line)
            if not m:
                continue
            src = int(m.group(1))
            dst = int(m.group(2))
            tail = m.group(3)
            paths = []
            weights = []
            mp = paths_re.search(tail)
            if mp:
                try:
                    paths = [int(x) for x in mp.group(2).split(",") if x != ""]
                except Exception:
                    paths = []
            ms = split_re.search(tail)
            if ms:
                try:
                    weights = [float(x) for x in ms.group(1).split(",") if x != ""]
                except Exception:
                    weights = []
            flows.append({"src": src, "dst": dst, "paths": paths, "weights": weights})
    return flows


def parse_id_name_map(datacenter_dir: Path, log_path: Path):
    """Return mapping from numeric ID to object name using parse_output -names."""
    rc, out = run([str(datacenter_dir.parent / "parse_output"), str(log_path), "-names"], cwd=str(datacenter_dir))
    mapping = {}
    if rc != 0:
        return mapping
    for line in out.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        # Format: "<id>\t<name>"
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            i = int(parts[0])
        except Exception:
            continue
        mapping[i] = parts[1]
    return mapping


def parse_cbr_sink_timeseries(datacenter_dir: Path, log_path: Path):
    """Extract time series samples for CBR_SINK records: {id: [(time_s, bytes_rcvd), ...]}"""
    cmd = [str(datacenter_dir.parent / "parse_output"), str(log_path), "-ascii", "-filter", "Type CBR_SINK"]
    rc, out = run(cmd, cwd=str(datacenter_dir))
    series = {}
    if rc != 0:
        return series
    # Example line: "123.456789000 Type CBR_SINK ID 66 Ev RATE BytesRcvd 10000 PktsRcvd 7 Rate 80000000"
    pat = re.compile(r"^(?P<time>[0-9]+\.[0-9]+)\s+Type CBR_SINK ID\s+(?P<id>\d+)\s+Ev RATE\s+BytesRcvd\s+(?P<bytes>\d+)\b")
    for line in out.splitlines():
        line = line.strip()
        # Skip echoes of filter argument or empty lines
        if not line or line.startswith("Type CBR_SINK"):
            continue
        m = pat.match(line)
        if not m:
            continue
        t = float(m.group("time"))
        sid = int(m.group("id"))
        b = int(m.group("bytes"))
        series.setdefault(sid, []).append((t, b))
    # Ensure time order
    for sid in list(series.keys()):
        series[sid].sort(key=lambda x: x[0])
    return series


def main():
    ap = argparse.ArgumentParser(description="Run HTSIM phases from a JSON manifest and summarize per-flow stats")
    ap.add_argument("manifest", help="Path to JSON manifest")
    ap.add_argument("--outdir", default="experiments", help="Root output directory")
    args = ap.parse_args()

    datacenter_dir = Path(__file__).resolve().parent.parent  # sim/datacenter
    ensure_binaries(datacenter_dir)

    manifest_path = Path(args.manifest).resolve()
    with manifest_path.open() as f:
        cfg = json.load(f)

    topo = cfg["topology"]
    global_rate = float(cfg.get("global_rate_mbps", 1000))
    default_phase_duration = float(cfg.get("default_phase_duration_sec", 1.0))
    timeline = cfg.get("timeline", [])
    tm_dir = cfg.get("tm_dir")

    # If tm_dir is provided and timeline is empty, auto-generate phases from TM files
    if (not timeline) and tm_dir:
        tm_root = Path(tm_dir)
        if not tm_root.is_dir():
            raise RuntimeError(f"tm_dir '{tm_dir}' does not exist or is not a directory")
        tms = sorted([p for p in tm_root.glob("*.tm")])
        if not tms:
            raise RuntimeError(f"No .tm files found under '{tm_dir}'")
        timeline = []
        for p in tms:
            timeline.append({
                "name": p.stem,
                "duration_sec": default_phase_duration,
                "tm_file": str(p)
            })

    # Only query hosts if we will write TMs
    nodes = None
    need_nodes = any("tm_file" not in phase for phase in timeline)
    if need_nodes:
        hosts = list_hosts(datacenter_dir, topo)
        nodes = len(hosts)

    exp_name = manifest_path.stem
    requested_out = Path(args.outdir)
    # If the requested outdir already ends with the experiment name, don't append it again
    if requested_out.name == exp_name:
        root_out = requested_out
    else:
        root_out = requested_out / exp_name
    (root_out / "tms").mkdir(parents=True, exist_ok=True)

    all_rows = []

    for phase in timeline:
        name = phase["name"]
        end_sec = float(phase.get("duration_sec", 1.0))
        fabric = phase.get("fabric_mbps")
        flows = phase.get("flows", [])
        tm_file = phase.get("tm_file")

        flows_decl = flows
        if tm_file:
            tm_path = Path(tm_file)
            # Parse declarations from the TM file for annotation purposes
            flows_decl = parse_tm_file(tm_path)
        else:
            if nodes is None:
                raise RuntimeError("Internal error: nodes unknown for TM generation")
            tm_path = root_out / "tms" / f"{name}.tm"
            write_tm(tm_path, nodes, flows)
            flows_decl = flows

        log_path = root_out / f"logout_{name}.dat"
        cmd = ["./htsim_cbr", "-json_topo", topo, "-tm", str(tm_path), "-o", str(log_path), "-rate", str(global_rate), "-end", str(end_sec)]
        if fabric is not None:
            cmd += ["-fabric_mbps", str(fabric)]
        print("Running:", " ".join(cmd))
        rc, out = run(cmd, cwd=str(datacenter_dir))
        if rc != 0:
            print(out)
            sys.exit(1)

        flow_stats = parse_flow_stats(out)
        tputs = parse_throughputs(datacenter_dir, log_path)
        id_name = parse_id_name_map(datacenter_dir, log_path)
        name_id = {v: k for (k, v) in id_name.items()}
        sink_series = parse_cbr_sink_timeseries(datacenter_dir, log_path)

        # Build rows
        for k, stat in flow_stats.items():
            src, dst, fid = k
            # find declared paths/weights for this (src,dst). If multiple entries, pick first match.
            decl = None
            for fl in flows_decl:
                try:
                    if int(fl["src"]) == src and int(fl["dst"]) == dst:
                        decl = fl
                        break
                except Exception:
                    pass
            paths = decl.get("paths", []) if decl else []
            weights = decl.get("weights", []) if decl else []
            mbps = tputs.get((src, dst, fid), None)
            # Compute active-time throughput for this flow
            sink_name = f"cbr_sink_{src}_{dst}_{fid}"
            active_duration = ""
            active_tput_mbps = ""
            sid = name_id.get(sink_name)
            flow_start_s = ""
            flow_finish_s = ""
            if sid is not None:
                samples = sink_series.get(sid, [])
                if samples:
                    prev_b = None
                    start_t = None
                    end_t = None
                    for (t, b) in samples:
                        if prev_b is None:
                            prev_b = b
                            continue
                        if b > prev_b:
                            if start_t is None:
                                start_t = t
                            end_t = t
                        prev_b = b
                    if start_t is not None and end_t is not None and end_t >= start_t:
                        flow_start_s = "{:.6f}".format(start_t)
                        flow_finish_s = "{:.6f}".format(end_t)
                        dur = end_t - start_t if end_t > start_t else 0.0
                        if dur > 0:
                            active_duration = "{:.6f}".format(dur)
                            arate = (stat["bytes_received"] * 8.0) / (dur * 1_000_000.0)
                            active_tput_mbps = "{:.3f}".format(arate)

            row = {
                "phase": name,
                "src": src,
                "dst": dst,
                "flow_id": fid,
                "paths": ";".join(str(p) for p in paths),
                "weights": ";".join(str(w) for w in weights),
                "bytes_sent": stat["bytes_sent"],
                "bytes_received": stat["bytes_received"],
                "bytes_dropped_est": max(stat["bytes_sent"] - stat["bytes_received"], 0),
                "throughput_mbps": ("{:.3f}".format(mbps) if mbps is not None else ""),
                "active_duration_s": active_duration,
                "active_throughput_mbps": active_tput_mbps,
                "flow_start_s": flow_start_s,
                "flow_finish_s": flow_finish_s
            }
            all_rows.append(row)

        # Write phase CSV
        csv_path = root_out / f"phase_{name}_summary.csv"
        with csv_path.open("w") as cf:
            headers = ["phase","src","dst","flow_id","paths","weights","bytes_sent","bytes_received","bytes_dropped_est","throughput_mbps","active_duration_s","active_throughput_mbps","flow_start_s","flow_finish_s"]
            cf.write(",".join(headers) + "\n")
            for r in all_rows:
                if r["phase"] != name:
                    continue
                cf.write(",".join(str(r[h]) for h in headers) + "\n")

    # Combined CSV
    combined = root_out / "all_phases.csv"
    with combined.open("w") as cf:
        headers = ["phase","src","dst","flow_id","paths","weights","bytes_sent","bytes_received","bytes_dropped_est","throughput_mbps","active_duration_s","active_throughput_mbps","flow_start_s","flow_finish_s"]
        cf.write(",".join(headers) + "\n")
        for r in all_rows:
            cf.write(",".join(str(r[h]) for h in headers) + "\n")

    print(f"Done. Outputs under {root_out}")


if __name__ == "__main__":
    main()
