"""Independent integrity check: compare SHA-256 of the sent file and the stored copy.
Usage: python tools/verify_received.py captured/face.jpg received/student01/face_...jpg"""
import hashlib
import sys

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()

a, b = sha(sys.argv[1]), sha(sys.argv[2])
print("sent    :", a)
print("received:", b)
print("MATCH" if a == b else "MISMATCH")
sys.exit(0 if a == b else 1)
