"""Creates a dummy 'biometric' file (random bytes) so the demo runs before Part A data is wired in."""
import os
import sys

size_kb = int(sys.argv[1]) if len(sys.argv) > 1 else 200
os.makedirs("captured", exist_ok=True)
with open("captured/sample_biometric.bin", "wb") as f:
    f.write(os.urandom(size_kb * 1024))
print(f"wrote captured/sample_biometric.bin ({size_kb} KiB)")
