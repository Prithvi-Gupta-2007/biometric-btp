
"""BTP receiver: receives biometric files, tracks progress and verifies integrity."""

import argparse
import hashlib
import json
import logging
import math
import os
import re
import socket
import socketserver
import sys
import time
import uuid

from . import protocol as P

log = logging.getLogger("btp.server")

SUBJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MODALITIES = {"face", "fingerprint", "iris", "voice", "other"}


def format_time(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{minutes:02d}:{seconds:02d}"


def show_progress(received, size, chunks_received, total_chunks,
                  start_time, crc_errors, duplicates):

    elapsed = time.perf_counter() - start_time

    percentage = received / size * 100 if size else 100
    speed = received / elapsed if elapsed > 0 else 0
    remaining = size - received
    eta = remaining / speed if speed > 0 else 0

    bar_width = 35
    filled = min(bar_width, int(bar_width * percentage / 100))
    bar = "█" * filled + "░" * (bar_width - filled)

    output = (
        "\033[H\033[J"
        "========== BTP LIVE RECEIVER ==========\n\n"
        f"Progress       : [{bar}] {percentage:6.2f}%\n"
        f"Chunks received: {chunks_received:,} / {total_chunks:,}\n"
        f"Data received  : {received / 1e9:.3f} / {size / 1e9:.3f} GB\n"
        f"Remaining      : {remaining / 1e9:.3f} GB\n"
        f"Speed          : {speed * 8 / 1e6:.2f} Mbps\n"
        f"Speed          : {speed / 1e6:.2f} MB/s\n"
        f"Elapsed        : {format_time(elapsed)}\n"
        f"ETA            : {format_time(eta)}\n\n"
        f"CRC errors     : {crc_errors}\n"
        f"Duplicates     : {duplicates}\n\n"
        "========================================\n"
    )

    sys.stdout.write(output)
    sys.stdout.flush()


def _sha256_file(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)

    return h.hexdigest()


def _validate_hello(meta):

    try:
        subject = str(meta["subject_id"])
        modality = str(meta.get("modality", "other"))
        filename = os.path.basename(str(meta["filename"])) or "data.bin"
        size = int(meta["size"])
        chunk = int(meta["chunk_size"])
        sha = str(meta["sha256"]).lower()

    except (KeyError, ValueError, TypeError):
        raise P.ProtocolError("malformed HELLO")

    if not SUBJECT_RE.match(subject):
        raise P.ProtocolError("invalid subject_id")

    if modality not in MODALITIES:
        raise P.ProtocolError("invalid modality")

    if not 0 < size <= P.MAX_FILE:
        raise P.ProtocolError("invalid size")

    if not 0 < chunk <= P.MAX_PAYLOAD:
        raise P.ProtocolError("invalid chunk_size")

    if not SHA_RE.match(sha):
        raise P.ProtocolError("invalid sha256")

    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)

    return dict(
        subject=subject,
        modality=modality,
        filename=filename,
        size=size,
        chunk=chunk,
        sha=sha,
        total=math.ceil(size / chunk)
    )


class Handler(socketserver.BaseRequestHandler):

    def handle(self):

        self.request.settimeout(self.server.timeout_s)
        io = P.FrameIO(self.request)

        try:
            self._session(io)

        except P.ProtocolError as e:

            log.warning("%s protocol error: %s", self.client_address, e)

            try:
                io.send_json(P.ERROR, {"error": str(e)})
            except OSError:
                pass

        except (ConnectionError, socket.timeout, OSError) as e:

            log.warning("%s connection problem: %s", self.client_address, e)

        except Exception:
            log.exception("%s unexpected error", self.client_address)

    def _session(self, io):

        t0 = time.perf_counter()

        ftype, _, payload, ok = io.recv()

        if ftype != P.HELLO or not ok:
            raise P.ProtocolError("expected valid HELLO")

        try:
            m = _validate_hello(json.loads(payload))

        except json.JSONDecodeError:
            raise P.ProtocolError("malformed HELLO")

        io.send_json(P.HELLO_ACK, {
            "status": "ready",
            "total_chunks": m["total"]
        })

        log.info(
            "%s receiving %s/%s (%d B, %d chunks)",
            self.client_address,
            m["subject"],
            m["filename"],
            m["size"],
            m["total"]
        )

        total = m["total"]
        chunk = m["chunk"]
        size = m["size"]

        part_dir = os.path.join(self.server.out_dir, ".partial")
        os.makedirs(part_dir, exist_ok=True)

        part = os.path.join(part_dir, uuid.uuid4().hex)

        # One byte per chunk: tracks whether a chunk was received.
        got = bytearray(total)

        n_got = 0
        received_bytes = 0
        crc_errors = 0
        duplicates = 0

        transfer_start = time.perf_counter()
        last_update = 0

        result = dict(
            ok=False,
            reason="",
            chunks_received=0,
            crc_errors=0,
            duplicates=0,
            expected_sha256=m["sha"],
            received_sha256=None,
            stored_as=None
        )

        try:

            with open(part, "wb") as f:

                while True:

                    ftype, seq, payload, ok = io.recv()

                    if ftype == P.DATA:

                        if not ok:
                            crc_errors += 1
                            continue

                        if seq < 0 or seq >= total:
                            raise P.ProtocolError("invalid chunk sequence")

                        want = (
                            chunk if seq < total - 1
                            else size - (total - 1) * chunk
                        )

                        if len(payload) != want:
                            raise P.ProtocolError("bad chunk length")

                        if got[seq]:

                            duplicates += 1

                        else:

                            f.seek(seq * chunk)
                            f.write(payload)

                            got[seq] = 1
                            n_got += 1
                            received_bytes += len(payload)

                        now = time.perf_counter()

                        if now - last_update >= 0.25 or n_got == total:

                            show_progress(
                                received_bytes,
                                size,
                                n_got,
                                total,
                                transfer_start,
                                crc_errors,
                                duplicates
                            )

                            last_update = now

                    elif ftype == P.SYNC and ok:

                        try:

                            info = json.loads(payload)

                            frm = max(0, int(info["from"]))
                            upto = min(int(info["upto"]), total - 1)

                            if frm > upto:
                                raise ValueError("invalid SYNC range")

                        except (ValueError, KeyError, TypeError):
                            raise P.ProtocolError("malformed SYNC")

                        io.send_json(
                            P.SYNC_ACK,
                            {
                                "missing": [
                                    s for s in range(frm, upto + 1)
                                    if not got[s]
                                ]
                            }
                        )

                        now = time.perf_counter()

                        if now - last_update >= 0.25:

                            show_progress(
                                received_bytes,
                                size,
                                n_got,
                                total,
                                transfer_start,
                                crc_errors,
                                duplicates
                            )

                            last_update = now

                    elif ftype == P.END and ok:

                        break

                    else:

                        raise P.ProtocolError("unexpected frame")

            # All chunks have been received.
            result.update(
                chunks_received=n_got,
                crc_errors=crc_errors,
                duplicates=duplicates
            )

            if n_got != total or received_bytes != size:

                result["reason"] = "missing chunks"

            else:

                # Verify SHA-256.
                digest = _sha256_file(part)
                result["received_sha256"] = digest

                if digest != m["sha"]:

                    result["reason"] = "SHA-256 mismatch (data corrupted or tampered)"

                else:

                    folder = os.path.join(
                        self.server.out_dir,
                        m["subject"]
                    )

                    os.makedirs(folder, exist_ok=True)

                    name = (
                        f"{m['modality']}_"
                        f"{time.strftime('%Y%m%d-%H%M%S')}_"
                        f"{m['filename']}"
                    )

                    path = os.path.join(folder, name)

                    n = 1

                    while os.path.exists(path):

                        path = os.path.join(
                            folder,
                            f"{n}_{name}"
                        )

                        n += 1

                    os.replace(part, path)

                    result.update(
                        ok=True,
                        reason="integrity verified",
                        stored_as=path
                    )

        finally:

            if os.path.exists(part):
                os.remove(part)

        result["server_time_s"] = round(
            time.perf_counter() - t0, 6
        )

        io.send_json(P.RESULT, result)

        # Save transfer details.
        with open(
            os.path.join(self.server.out_dir, "transfers.jsonl"),
            "a"
        ) as f:

            f.write(
                json.dumps({
                    "time": time.strftime("%F %T"),
                    "client": self.client_address[0],
                    "subject": m["subject"],
                    **result
                }) + "\n"
            )

        # Final receiver report.
        print("\n========== BTP RECEIVER REPORT ==========")

        print(f"File received    : {m['filename']}")
        print(f"File size        : {size / (1024**2):.2f} MB")
        print(f"Chunk size       : {chunk / 1024:.0f} KB")
        print(f"Total chunks     : {total:,}")
        print(f"Received chunks  : {n_got:,}")
        print(f"Transfer time    : {result['server_time_s']:.2f} seconds")

        speed = (
            received_bytes * 8 / result["server_time_s"] / 1e6
            if result["server_time_s"] > 0 else 0
        )

        print(f"Receive speed    : {speed:.2f} Mbps")
        print(f"CRC errors       : {crc_errors}")
        print(f"Duplicates       : {duplicates}")

        print("-----------------------------------------")

        print(f"SHA-256          : {result['received_sha256']}")
        print(f"Integrity        : {'VERIFIED' if result['ok'] else 'FAILED'}")
        print(f"Status           : {'SUCCESS' if result['ok'] else 'FAILED'}")

        print("=========================================\n", flush=True)

        log.info(
            "%s -> %s",
            self.client_address,
            result["reason"]
        )


class BTPServer(socketserver.ThreadingTCPServer):

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        host="0.0.0.0",
        port=5000,
        out_dir="received",
        timeout_s=30
    ):

        os.makedirs(out_dir, exist_ok=True)

        self.out_dir = out_dir
        self.timeout_s = timeout_s

        super().__init__((host, port), Handler)

    @property
    def port(self):
        return self.server_address[1]


def main():

    ap = argparse.ArgumentParser(
        description="BTP biometric receiver"
    )

    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--out", default="received")

    a = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    srv = BTPServer(
        a.host,
        a.port,
        a.out
    )

    log.info(
        "BTP server listening on %s:%d, saving to %s/",
        a.host,
        srv.port,
        a.out
    )

    try:
        srv.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
