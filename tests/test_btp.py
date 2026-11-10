"""Run:  python -m unittest discover -s tests -v"""
import hashlib
import os
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from btp import protocol as P
from btp.client import send_data, send_file
from btp.server import BTPServer


class BTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = BTPServer("127.0.0.1", 0, cls.tmp.name, timeout_s=5)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.data = os.urandom(100_003)           # deliberately not a multiple of the chunk size

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def send(self, **kw):
        return send_data("127.0.0.1", self.srv.port, kw.pop("data", self.data), **kw)

    def stored(self, subject):
        folder = os.path.join(self.tmp.name, subject)
        files = sorted(os.listdir(folder))
        with open(os.path.join(folder, files[-1]), "rb") as f:
            return f.read()

    def test_roundtrip_is_bit_exact(self):
        m = self.send(subject="t_roundtrip", chunk_size=4096, window=8)
        self.assertTrue(m["ok"])
        self.assertEqual(self.stored("t_roundtrip"), self.data)
        self.assertEqual(m["sha256"], hashlib.sha256(self.data).hexdigest())

    def test_single_chunk_and_tiny_file(self):
        m = self.send(subject="t_tiny", data=b"x", chunk_size=4096)
        self.assertTrue(m["ok"])
        self.assertEqual(self.stored("t_tiny"), b"x")

    def test_corrupted_chunks_are_detected_and_retransmitted(self):
        m = self.send(subject="t_corrupt", chunk_size=1024, window=16, corrupt_prob=0.2, seed=1)
        self.assertTrue(m["ok"])
        self.assertGreater(m["injected_corruptions"], 0)
        self.assertEqual(m["retransmissions"], m["injected_corruptions"])
        self.assertEqual(self.stored("t_corrupt"), self.data)

    def test_streamed_file_from_disk(self):
        path = os.path.join(self.tmp.name, "src.bin")
        with open(path, "wb") as f:
            f.write(self.data * 30)                          # ~3 MB, many chunks
        m = send_file("127.0.0.1", self.srv.port, path, subject="t_file", chunk_size=65536, window=32)
        self.assertTrue(m["ok"])
        self.assertEqual(self.stored("t_file"), self.data * 30)
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, ".partial")), [])   # temp file cleaned up

    def test_stop_and_wait_window_1(self):
        self.assertTrue(self.send(subject="t_saw", data=self.data[:20000], chunk_size=2048, window=1)["ok"])

    def test_tampered_hash_is_rejected(self):
        m = self.send(subject="t_tamper", _tamper_sha=True)
        self.assertFalse(m["ok"])
        self.assertIn("mismatch", m["server_reason"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "t_tamper")))   # nothing stored

    def test_path_traversal_and_bad_subject_rejected(self):
        with self.assertRaises(P.ProtocolError):
            self.send(subject="../../etc")
        m = self.send(subject="t_name", filename="../../evil.bin")
        self.assertTrue(m["ok"])
        for root, _, files in os.walk(self.tmp.name):
            self.assertTrue(os.path.realpath(root).startswith(os.path.realpath(self.tmp.name)))

    def test_garbage_input_does_not_crash_server(self):
        with socket.create_connection(("127.0.0.1", self.srv.port), timeout=3) as s:
            s.sendall(b"GET / HTTP/1.1\r\n\r\n" + b"A" * 50)
            s.settimeout(2)
            try:
                s.recv(1024)
            except OSError:
                pass
        self.assertTrue(self.send(subject="t_after_garbage", data=b"hello")["ok"])


if __name__ == "__main__":
    unittest.main()
