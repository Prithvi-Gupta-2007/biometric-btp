# BTP specification (v1)

## Frame
```
| magic "BT" 2B | version 1B | type 1B | seq 4B | length 4B | payload | CRC32 4B |
```
Network byte order. CRC32 = `zlib.crc32(header || payload)`. Max payload 1 MiB, max file 32 GiB (streamed to disk).

| type | name | direction | payload |
|---|---|---|---|
| 1 | HELLO | C→S | JSON: subject_id, modality, filename, size, chunk_size, sha256 |
| 2 | HELLO_ACK | S→C | JSON: status, total_chunks |
| 3 | DATA | C→S | `seq` = chunk index, payload = raw bytes |
| 4 | SYNC | C→S | JSON: `{"upto": last_seq_sent}` |
| 5 | SYNC_ACK | S→C | JSON: `{"missing": [seq, ...]}` |
| 6 | END | C→S | – |
| 7 | RESULT | S→C | JSON: ok, reason, received_sha256, crc_errors, stored_as, ... |
| 8 | ERROR | S→C | JSON: error |

## Session
```
Client                                   Server
  HELLO ------------------------------->  validate, allocate
  <------------------------------ HELLO_ACK
  DATA(0..W-1) ----------------------->  CRC ok -> store; CRC bad -> drop (counted)
  SYNC(upto=W-1) --------------------->
  <------------------------ SYNC_ACK(missing=[3,7])
  DATA(3), DATA(7) ------------------->  (repeat SYNC until missing=[], next window)
  ...
  END --------------------------------->  reassemble, SHA-256 == HELLO.sha256 ?
  <---------------------------- RESULT(ok, reason, received_sha256)
```
The client treats the transfer as successful only if `RESULT.ok` and the server's hash equals its own.

## Design notes
* **Why TCP underneath?** It already gives ordered, reliable bytes; BTP adds what TCP cannot: message framing,
  per-chunk integrity (TCP's 16-bit checksum is weak), end-to-end verification of the *whole file*, and
  explicit selective repair that we can test and measure.
* **Window** = number of chunks sent before one SYNC round-trip. `window=1` is stop-and-wait (1 RTT per chunk);
  throughput on a link with round-trip time RTT ≈ `window × chunk_size / RTT` until bandwidth-limited.
* **Overhead** per chunk = 14 B header+CRC; relative overhead ≈ `14 / chunk_size` (+ SYNC traffic).
* **Fault injection**: `--corrupt-prob p` flips a payload byte after the CRC is computed, emulating bit errors.
