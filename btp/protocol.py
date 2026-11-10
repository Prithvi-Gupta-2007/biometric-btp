"""
BTP wire format
===============
Every message (frame) on the TCP stream looks like this:

    +-------+---------+------+---------+----------+-----------+---------+
    | magic | version | type |   seq   |  length  |  payload  |  CRC32  |
    |  2 B  |   1 B   | 1 B  |   4 B   |   4 B    | length B  |   4 B   |
    +-------+---------+------+---------+----------+-----------+---------+

* CRC32 covers header + payload (detects corruption of every single chunk).
* TCP is a byte stream, so framing (the length field) is what lets the
  receiver find message boundaries.
"""
import json
import socket
import struct
import zlib

MAGIC = b"BT"
VERSION = 1

# frame types
HELLO, HELLO_ACK, DATA, SYNC, SYNC_ACK, END, RESULT, ERROR = range(1, 9)
TYPE_NAMES = {1: "HELLO", 2: "HELLO_ACK", 3: "DATA", 4: "SYNC",
              5: "SYNC_ACK", 6: "END", 7: "RESULT", 8: "ERROR"}

HEADER = struct.Struct("!2sBBII")   # magic, version, type, seq, length
TRAILER = struct.Struct("!I")       # crc32

MAX_PAYLOAD = 1 << 20               # 1 MiB per frame
MAX_FILE = 32 << 30                 # 32 GiB per file (streamed to disk, never held in RAM)


class ProtocolError(Exception):
    """Peer violated the protocol (bad magic, bad CRC on control frame, ...)."""


class FrameIO:
    """Sends / receives BTP frames on a connected TCP socket and counts bytes."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.bytes_sent = 0
        self.bytes_recv = 0
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            part = self.sock.recv(n - len(buf))
            if not part:
                raise ConnectionError("peer closed the connection")
            buf += part
        return bytes(buf)

    def send(self, ftype: int, seq: int = 0, payload: bytes = b"",
             corrupt: bool = False) -> None:
        """corrupt=True flips a payload byte AFTER the CRC is computed
        (fault injection used by the tests / benchmarks)."""
        header = HEADER.pack(MAGIC, VERSION, ftype, seq, len(payload))
        crc = zlib.crc32(header + payload) & 0xFFFFFFFF
        if corrupt and payload:
            payload = bytes([payload[0] ^ 0xFF]) + payload[1:]
        frame = header + payload + TRAILER.pack(crc)
        self.sock.sendall(frame)
        self.bytes_sent += len(frame)

    def send_json(self, ftype: int, obj: dict, seq: int = 0) -> None:
        self.send(ftype, seq, json.dumps(obj).encode())

    def recv(self):
        """Returns (type, seq, payload, crc_ok)."""
        header = self._recv_exact(HEADER.size)
        magic, ver, ftype, seq, length = HEADER.unpack(header)
        if magic != MAGIC or ver != VERSION:
            raise ProtocolError("bad magic/version")
        if length > MAX_PAYLOAD:
            raise ProtocolError("frame too large")
        payload = self._recv_exact(length)
        (crc,) = TRAILER.unpack(self._recv_exact(TRAILER.size))
        self.bytes_recv += HEADER.size + length + TRAILER.size
        crc_ok = crc == (zlib.crc32(header + payload) & 0xFFFFFFFF)
        return ftype, seq, payload, crc_ok

    def recv_json(self, expect: int):
        ftype, _, payload, ok = self.recv()
        if ftype == ERROR:
            raise ProtocolError("peer error: " + json.loads(payload).get("error", "?"))
        if ftype != expect or not ok:
            raise ProtocolError(f"expected {TYPE_NAMES[expect]}, got {TYPE_NAMES.get(ftype, ftype)} (crc_ok={ok})")
        return json.loads(payload)
