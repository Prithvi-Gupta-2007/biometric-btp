
"""BTP sender: streams biometric files, repairs lost chunks and verifies integrity."""

import argparse
import hashlib
import json
import math
import os
import random
import socket
import sys
import time

from . import protocol as P

MODALITIES = ["face", "fingerprint", "iris", "voice", "other"]


def format_time(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def show_progress(completed, total_size, start_time, chunks_done, total_chunks):
    elapsed = time.perf_counter() - start_time

    percentage = completed / total_size * 100 if total_size else 100
    speed = completed / elapsed if elapsed > 0 else 0
    remaining = total_size - completed
    eta = remaining / speed if speed > 0 else 0

    bar_width = 35
    filled = min(bar_width, int(bar_width * percentage / 100))
    bar = "█" * filled + "░" * (bar_width - filled)

    output = (
        "\033[H\033[J"
        "========== BTP LIVE TRANSFER ==========\n\n"
        f"File progress : [{bar}] {percentage:6.2f}%\n"
        f"Chunks sent   : {chunks_done:,} / {total_chunks:,}\n"
        f"Data sent     : {completed / 1e9:.3f} / {total_size / 1e9:.3f} GB\n"
        f"Remaining     : {remaining / 1e9:.3f} GB\n"
        f"Speed         : {speed * 8 / 1e6:.2f} Mbps\n"
        f"Elapsed       : {format_time(elapsed)}\n"
        f"ETA           : {format_time(eta)}\n\n"
        "========================================\n"
    )

    sys.stdout.write(output)
    sys.stdout.flush()


def _transfer(host, port, size, sha, read_chunk, filename, subject,
              modality, chunk_size, window, corrupt_prob, seed,
              timeout, tamper_sha=False, live=True):

    rng = random.Random(seed)
    total = math.ceil(size / chunk_size)

    m = dict(
        ok=False,
        bytes=size,
        chunks=total,
        chunk_size=chunk_size,
        window=window,
        retransmissions=0,
        sync_rounds=0,
        injected_corruptions=0,
        sha256=sha
    )

    t0 = time.perf_counter()
    completed = 0
    chunks_done = 0
    last_update = 0

    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        io = P.FrameIO(s)

        io.send_json(P.HELLO, dict(
            subject_id=subject,
            modality=modality,
            filename=filename,
            size=size,
            chunk_size=chunk_size,
            sha256=("0" * 64) if tamper_sha else sha
        ))

        io.recv_json(P.HELLO_ACK)

        if live:
            show_progress(0, size, t0, 0, total)

        for start in range(0, total, window):
            end = min(start + window, total)

            for seq in range(start, end):
                chunk = read_chunk(seq)

                bad = corrupt_prob > 0 and rng.random() < corrupt_prob
                m["injected_corruptions"] += bad

                io.send(P.DATA, seq, chunk, corrupt=bad)

                completed += len(chunk)
                chunks_done += 1

                now = time.perf_counter()

                if live and (now - last_update >= 0.25 or chunks_done == total):
                    show_progress(
                        completed, size, t0, chunks_done, total
                    )
                    last_update = now

            for _ in range(20):
                io.send_json(P.SYNC, {
                    "from": start,
                    "upto": end - 1
                })

                m["sync_rounds"] += 1

                missing = io.recv_json(P.SYNC_ACK)["missing"]

                if not missing:
                    break

                for seq in missing:
                    io.send(P.DATA, seq, read_chunk(seq))
                    m["retransmissions"] += 1

            else:
                raise P.ProtocolError("Could not repair window")

        io.send(P.END)

        res = io.recv_json(P.RESULT)

        m["time_s"] = time.perf_counter() - t0
        m["wire_bytes"] = io.bytes_sent + io.bytes_recv

    m["ok"] = (
        bool(res["ok"]) and
        res["received_sha256"] == sha
    )

    m["server_reason"] = res["reason"]

    m["throughput_mbps"] = (
        size * 8 / m["time_s"] / 1e6
        if m["time_s"] > 0 else 0
    )

    m["overhead_pct"] = (
        (m["wire_bytes"] / size - 1) * 100
        if size > 0 else 0
    )

    return m


def send_data(host, port, data, filename="biometric.bin",
              subject="student01", modality="face",
              chunk_size=4096, window=16,
              corrupt_prob=0.0, seed=None,
              timeout=30, _tamper_sha=False):

    sha = hashlib.sha256(data).hexdigest()

    return _transfer(
        host, port,
        len(data), sha,
        lambda i: data[i * chunk_size:(i + 1) * chunk_size],
        filename, subject, modality,
        chunk_size, window,
        corrupt_prob, seed, timeout,
        _tamper_sha,
        live=False
    )


def send_file(host, port, path,
              subject="student01", modality="face",
              chunk_size=65536, window=64,
              corrupt_prob=0.0, seed=None,
              timeout=30, live=True):

    h = hashlib.sha256()

    # First pass: calculate SHA-256
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    size = os.path.getsize(path)
    sha = h.hexdigest()

    # Second pass: stream file in chunks
    with open(path, "rb") as f:

        def read_chunk(i):
            f.seek(i * chunk_size)
            return f.read(chunk_size)

        return _transfer(
            host, port,
            size, sha,
            read_chunk,
            os.path.basename(path),
            subject, modality,
            chunk_size, window,
            corrupt_prob, seed, timeout,
            live=live
        )


def print_report(path, m):

    print("\n========== BTP TRANSFER REPORT ==========")

    print(f"File              : {os.path.basename(path)}")
    print(f"File size         : {m['bytes'] / (1024**2):.2f} MB")
    print(f"Chunk size        : {m['chunk_size'] / 1024:.0f} KB")
    print(f"Total chunks      : {m['chunks']:,}")
    print(f"Window size       : {m['window']} chunks")

    print("-----------------------------------------")

    print(f"Transfer time     : {m['time_s']:.2f} seconds")
    print(f"Throughput        : {m['throughput_mbps']:.2f} Mbps")
    print(f"Speed             : {m['throughput_mbps'] / 8:.2f} MB/s")

    print("-----------------------------------------")

    print(f"Retransmissions   : {m['retransmissions']}")
    print(f"Corrupted chunks  : {m['injected_corruptions']}")
    print(f"SYNC rounds       : {m['sync_rounds']}")
    print(f"Protocol overhead : {m['overhead_pct']:.2f}%")

    print("-----------------------------------------")

    print(f"SHA-256           : {m['sha256']}")
    print(f"Integrity         : {'VERIFIED' if m['ok'] else 'FAILED'}")
    print(f"Status            : {'SUCCESS' if m['ok'] else 'FAILED'}")

    print("=========================================\n", flush=True)


def main():

    ap = argparse.ArgumentParser(description="BTP biometric sender")

    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)

    group = ap.add_mutually_exclusive_group(required=True)

    group.add_argument("--file", help="Send one file")
    group.add_argument("--dir", help="Send all files in a folder")

    ap.add_argument("--subject", default="student01")

    ap.add_argument(
        "--modality",
        default="face",
        choices=MODALITIES
    )

    ap.add_argument(
        "--chunk-size",
        type=int,
        default=65536,
        help="Chunk size in bytes (default 64 KiB)"
    )

    ap.add_argument(
        "--window",
        type=int,
        default=64,
        help="Chunks per SYNC round (default 64)"
    )

    ap.add_argument(
        "--corrupt-prob",
        type=float,
        default=0.0
    )

    ap.add_argument(
        "--retries",
        type=int,
        default=3
    )

    ap.add_argument(
        "--json",
        action="store_true"
    )

    a = ap.parse_args()

    if a.chunk_size <= 0 or a.window <= 0:
        ap.error("Chunk size and window must be positive")

    if not 0 <= a.corrupt_prob <= 1:
        ap.error("Corruption probability must be between 0 and 1")

    if a.file:
        files = [a.file]

    else:
        files = sorted(
            os.path.join(a.dir, name)
            for name in os.listdir(a.dir)
            if os.path.isfile(os.path.join(a.dir, name))
            and os.path.getsize(os.path.join(a.dir, name)) > 0
        )

        if not files:
            sys.exit("No files found in " + a.dir)

    t0 = time.perf_counter()

    sent = 0
    okc = 0
    results = []

    for i, path in enumerate(files, 1):

        m = None

        for attempt in range(1, a.retries + 1):

            try:
                m = send_file(
                    a.host,
                    a.port,
                    path,
                    a.subject,
                    a.modality,
                    a.chunk_size,
                    a.window,
                    a.corrupt_prob,
                    live=not a.json
                )

                if m["ok"]:
                    break

            except (OSError, P.ProtocolError) as e:

                if not a.json:
                    print(
                        f"\nAttempt {attempt}/{a.retries} failed: {e}",
                        flush=True
                    )

        if m is None:
            print(f"\n[FAIL] {os.path.basename(path)}")
            results.append({
                "file": path,
                "ok": False
            })
            continue

        if not a.json:
            print_report(path, m)

        sent += m["bytes"] if m["ok"] else 0
        okc += int(m["ok"])

        results.append({
            "file": path,
            **m
        })

    dt = time.perf_counter() - t0

    if a.json:
        print(json.dumps(results, indent=2))

    else:
        print("\n========== FINAL SUMMARY ==========")

        print(f"Files transferred : {okc}/{len(files)}")
        print(f"Total data        : {sent / 1e9:.3f} GB")
        print(f"Total time        : {dt:.2f} seconds")

        avg_speed = sent * 8 / dt / 1e6 if dt > 0 else 0

        print(f"Average speed     : {avg_speed:.2f} Mbps")

        print(
            f"Overall status    : "
            f"{'SUCCESS' if okc == len(files) else 'FAILED'}"
        )

        print("===================================")

    sys.exit(0 if okc == len(files) else 1)


if __name__ == "__main__":
    main()
