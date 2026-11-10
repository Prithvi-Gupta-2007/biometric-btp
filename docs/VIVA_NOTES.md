# Viva cheat-sheet (read the code once end-to-end before the viva!)

1. **Which layer / protocol?** Custom application-layer protocol (BTP) on top of TCP (transport layer, port 5000).
2. **Why framing?** TCP is a stream with no message boundaries → length-prefixed frames.
3. **How is integrity verified?** CRC32 per chunk (find the bad chunk) + SHA-256 of the whole file (end-to-end proof). Hash is mismatch → file is not stored.
4. **What if a chunk is corrupted?** Receiver drops it, reports it in `SYNC_ACK.missing`, sender retransmits only that chunk (selective repeat).
5. **What does `window` do?** Chunks sent per SYNC round-trip. 1 = stop-and-wait; larger = pipelining. Experiment 2 shows time falling ~linearly with window on a 40 ms RTT link.
6. **Why does throughput rise with chunk size?** Fixed 14 B header/CRC and per-frame Python/syscall cost are amortised (Exp. 1).
7. **Why not UDP?** UDP would require implementing sequencing, ACKs, timers, congestion control ourselves; TCP + application-level verification meets all requirements with less risk. (Extension: same BTP frames over UDP + timeout-based retransmit.)
8. **Security limits?** CRC/SHA don't stop an attacker; add TLS for confidentiality/authenticity.
9. **How do you handle malicious input?** Size caps, regex-validated subject id, sanitized filename (no path traversal), socket timeouts, unknown frames → ERROR + close.
10. **How do you test it?** `tests/test_btp.py` + `benchmark/run_benchmark.py`.
