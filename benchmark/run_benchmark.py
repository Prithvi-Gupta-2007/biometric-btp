"""
Performance evaluation of BTP.  Run from the repo root:

    python benchmark/run_benchmark.py            # full (about 1-2 min)
    python benchmark/run_benchmark.py --quick    # fast smoke run

Experiments (each point = mean of --repeats runs, all on localhost):
  1. chunk size sweep         -> throughput, protocol overhead
  2. window size sweep        -> transmission time on a 40 ms RTT link (netem proxy)
  3. corruption-rate sweep    -> retransmissions, transmission time, success rate
Outputs: results/benchmark.csv, results/*.png (if matplotlib is installed), markdown table on stdout.
"""
import argparse
import csv
import os
import statistics as st
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from btp.client import send_data
from btp.netem_proxy import Proxy
from btp.server import BTPServer

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def run(data, port, repeats, **kw):
    runs = [send_data("127.0.0.1", port, data, **kw) for _ in range(repeats)]
    ok = sum(r["ok"] for r in runs)
    f = lambda k: st.mean(r[k] for r in runs)
    return dict(time_ms=f("time_s") * 1000, throughput_mbps=f("throughput_mbps"),
                overhead_pct=f("overhead_pct"), retransmissions=f("retransmissions"),
                sync_rounds=f("sync_rounds"), success_rate_pct=100 * ok / repeats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--repeats", type=int, default=None)
    a = ap.parse_args()
    reps = a.repeats or (1 if a.quick else 5)
    big = os.urandom((512 if a.quick else 4096) * 1024)
    small = os.urandom(256 * 1024)

    tmp = tempfile.TemporaryDirectory()
    srv = BTPServer("127.0.0.1", 0, tmp.name)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    proxy = Proxy("127.0.0.1", srv.port, delay_ms=20).start()          # 20 ms each way = 40 ms RTT
    rows = []

    def add(exp, param, value, res):
        rows.append(dict(experiment=exp, parameter=param, value=value, **{k: round(v, 3) for k, v in res.items()}))
        print(f"  {exp:10s} {param}={value:<7} time={res['time_ms']:9.1f} ms  "
              f"thr={res['throughput_mbps']:8.2f} Mbit/s  ovhd={res['overhead_pct']:5.2f}%  "
              f"retx={res['retransmissions']:6.1f}  ok={res['success_rate_pct']:.0f}%", flush=True)

    print("Exp 1: chunk size (localhost, window=16)")
    for cs in (256, 512, 1024, 4096, 16384, 65536):
        add("chunk", "chunk_size", cs, run(big, srv.port, reps, chunk_size=cs, window=16))

    print("Exp 2: window size (40 ms RTT, chunk=4096, 256 KiB file)")
    for w in (1, 2, 4, 8, 16, 64):
        add("window", "window", w, run(small, proxy.port, max(1, reps // 2), chunk_size=4096, window=w))

    print("Exp 3: corruption probability (localhost, chunk=1024, window=16)")
    for p in (0.0, 0.01, 0.05, 0.10, 0.20):
        add("corruption", "corrupt_prob", p, run(small, srv.port, reps, chunk_size=1024, window=16, corrupt_prob=p))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "benchmark.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {os.path.join(OUT, 'benchmark.csv')}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - skipping plots (pip install matplotlib)")
        return
    def plot(exp, ycol, ylabel, title, fname, xlabel, log=False):
        sub = [r for r in rows if r["experiment"] == exp]
        xs = [str(r["value"]) for r in sub]
        fig, ax = plt.subplots(figsize=(5, 3.2))
        ax.plot(xs, [r[ycol] for r in sub], marker="o")
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title); ax.grid(alpha=.3)
        if log: ax.set_yscale("log")
        fig.tight_layout(); fig.savefig(os.path.join(OUT, fname), dpi=150); plt.close(fig)
    plot("chunk", "throughput_mbps", "Throughput (Mbit/s)", "Throughput vs chunk size", "chunk_throughput.png", "chunk size (B)")
    plot("chunk", "overhead_pct", "Protocol overhead (%)", "Overhead vs chunk size", "chunk_overhead.png", "chunk size (B)")
    plot("window", "time_ms", "Transfer time (ms)", "Time vs window (RTT 40 ms)", "window_time.png", "window (chunks per SYNC)", log=True)
    plot("corruption", "retransmissions", "Retransmitted chunks", "Retransmissions vs corruption", "corruption_retx.png", "corruption probability")
    plot("corruption", "time_ms", "Transfer time (ms)", "Time vs corruption", "corruption_time.png", "corruption probability")
    print("wrote plots to results/")
    proxy.stop(); srv.shutdown()


if __name__ == "__main__":
    main()
