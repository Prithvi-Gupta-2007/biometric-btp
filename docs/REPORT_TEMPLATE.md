# Part B Technical Report – BTP: Biometric Transfer over TCP  (max 2 pages)
Team: ______  Members: ______  Repo: ______

## 1. Problem and scenario
Biometric data (face image / fingerprint) captured in Part A by the student app must reach the attendance
backend intact. We designed an application-layer protocol (BTP) over TCP that transfers the file, detects
corruption per chunk, repairs it selectively and proves end-to-end integrity with SHA-256.

## 2. Architecture
(insert `docs/architecture.png`)  Sender (chunker, framing, windowed sender) ↔ TCP ↔ Receiver (deframer, reassembly, verification, storage).

## 3. Protocol design
Frame format, message types and session flow – summarise `docs/protocol.md` (table + sequence).
Mechanisms: framing, CRC32/chunk, SYNC/SYNC_ACK selective retransmission, window, SHA-256, input validation.

## 4. Implementation
Python 3 stdlib (`socket`, `socketserver`, `zlib`, `hashlib`); threaded server; ~400 lines. Real biometric file
from Part A sent unchanged; receiver stores `received/<subject>/<modality>_<time>_<file>` and logs to `transfers.jsonl`.

## 5. Testing
Unit/integration tests (8): bit-exact roundtrip, single/odd-sized files, injected corruption → retransmission,
tampered hash → rejected and not stored, path traversal / invalid subject rejected, garbage input survives.
Screenshot: server log + client output + `verify_received.py` MATCH.

## 6. Performance evaluation  (paste YOUR numbers from results/benchmark.csv)
| Experiment | Parameter | Result |
|---|---|---|
| Chunk size | 256 B … 64 KiB | throughput ___ → ___ Mbit/s; overhead ___% → ___% |
| Window (RTT 40 ms) | 1 … 64 | time ___ ms → ___ ms |
| Corruption | 0 … 20 % | retransmissions ___ → ___; success rate ___% |
(insert 2–3 plots from `results/`)
Discussion: why throughput increases with chunk size; why window cuts latency-bound time; cost of retransmission.

## 7. Limitations and future work
No confidentiality (add TLS); retransmission relies on TCP being reliable otherwise; UDP variant with timers; resume support.
