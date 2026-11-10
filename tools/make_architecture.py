"""Generates docs/architecture.png (system architecture diagram for the report)."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(11, 4.6))
ax.set_xlim(0, 11); ax.set_ylim(0, 4.6); ax.axis("off")

def box(x, y, w, h, text, fc):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04", fc=fc, ec="#333", lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8.5)

def arrow(x1, y1, x2, y2, label="", both=False):
    ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="<->" if both else "->", lw=1.3))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, label, ha="center", fontsize=8)

ax.text(1.75, 4.35, "SENDER (student device)", ha="center", fontweight="bold")
ax.text(9.25, 4.35, "RECEIVER (attendance backend)", ha="center", fontweight="bold")
box(0.2, 3.2, 3.1, 0.8, "Part A: biometric capture\n(face image / fingerprint)", "#dbeafe")
box(0.2, 2.1, 3.1, 0.8, "Chunker + SHA-256 of whole file\n(btp/client.py)", "#e0e7ff")
box(0.2, 1.0, 3.1, 0.8, "BTP framing: header + payload + CRC32\nwindowed send, SYNC, retransmit", "#e0e7ff")
box(7.7, 1.0, 3.1, 0.8, "BTP deframer: CRC32 check per chunk\nSYNC_ACK(missing list)  (btp/server.py)", "#dcfce7")
box(7.7, 2.1, 3.1, 0.8, "Reassembly + SHA-256 verification\nRESULT (ok / mismatch)", "#dcfce7")
box(7.7, 3.2, 3.1, 0.8, "Storage: received/<subject>/...\n+ transfers.jsonl audit log", "#fef9c3")
for y in (3.2, 2.1):
    ax.annotate("", (1.75, y - 0.3), (1.75, y), arrowprops=dict(arrowstyle="->", lw=1.3))
ax.annotate("", (9.25, 2.1), (9.25, 1.8), arrowprops=dict(arrowstyle="->", lw=1.3))
ax.annotate("", (9.25, 3.2), (9.25, 2.9), arrowprops=dict(arrowstyle="->", lw=1.3))
box(4.2, 0.9, 2.6, 1.0, "TCP connection (transport layer)\nreliable byte stream\n[optional netem proxy:\ndelay / bandwidth cap]", "#fee2e2")
arrow(3.3, 1.4, 4.2, 1.4, both=True)
arrow(6.8, 1.4, 7.7, 1.4, both=True)
ax.text(5.5, 0.35, "HELLO -> HELLO_ACK -> DATA* / SYNC <-> SYNC_ACK -> END -> RESULT", ha="center", fontsize=9, style="italic")
fig.savefig("docs/architecture.png", dpi=170, bbox_inches="tight")
