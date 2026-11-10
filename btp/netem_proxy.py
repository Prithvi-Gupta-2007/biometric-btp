"""Tiny TCP proxy that emulates a slow link (one-way delay + bandwidth cap).
Lets you measure the protocol on a 'bad network' without root / tc-netem."""
import argparse
import queue
import socket
import threading
import time


class Proxy:
    def __init__(self, target_host, target_port, listen_host="127.0.0.1", listen_port=0,
                 delay_ms=0.0, rate_kbps=0):
        self.target = (target_host, target_port)
        self.delay = delay_ms / 1000.0
        self.rate_bps = rate_kbps * 1000.0
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((listen_host, listen_port))
        self.srv.listen(16)
        self.srv.settimeout(0.3)
        self.port = self.srv.getsockname()[1]
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        self.srv.close()

    def _accept(self):
        while not self._stop.is_set():
            try:
                c, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                u = socket.create_connection(self.target)
            except OSError:
                c.close()
                continue
            for a, b in ((c, u), (u, c)):
                threading.Thread(target=self._pump, args=(a, b), daemon=True).start()

    def _pump(self, src, dst):
        q = queue.Queue()

        def reader():
            try:
                while (d := src.recv(65536)):
                    q.put((time.monotonic() + self.delay, d))
            except OSError:
                pass
            q.put(None)

        threading.Thread(target=reader, daemon=True).start()
        try:
            while (item := q.get()) is not None:
                due, d = item
                wait = due - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                if self.rate_bps:
                    time.sleep(len(d) * 8 / self.rate_bps)
                dst.sendall(d)
        except OSError:
            pass
        finally:
            for s in (dst, src):
                try:
                    s.shutdown(socket.SHUT_WR)
                except OSError:
                    pass


def main():
    ap = argparse.ArgumentParser(description="Slow-link emulator for BTP experiments")
    ap.add_argument("--listen-port", type=int, default=6000)
    ap.add_argument("--target-host", default="127.0.0.1")
    ap.add_argument("--target-port", type=int, default=5000)
    ap.add_argument("--delay-ms", type=float, default=20, help="one-way delay")
    ap.add_argument("--rate-kbps", type=float, default=0, help="0 = unlimited")
    a = ap.parse_args()
    p = Proxy(a.target_host, a.target_port, "0.0.0.0", a.listen_port, a.delay_ms, a.rate_kbps).start()
    print(f"proxy :{p.port} -> {a.target_host}:{a.target_port}  delay={a.delay_ms}ms rate={a.rate_kbps}kbps")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
