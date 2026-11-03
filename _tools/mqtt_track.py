"""Track every live (non-retained) message with timestamps for a long window.

Usage: python mqtt_track.py <seconds> [serial-filter]

Writes a per-device summary plus a raw timeline to _tools/mqtt-track.txt.
"""
from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"
seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 360
serial_filter = sys.argv[2] if len(sys.argv) > 2 else None

live: Counter[str] = Counter()
first_seen: dict[str, str] = {}
last_seen: dict[str, str] = {}
samples: dict[str, list[str]] = defaultdict(list)
timeline: list[str] = []
t0 = time.time()


def on_connect(c, u, flags, rc):
    c.subscribe("#", qos=0)


def on_message(c, u, msg):
    if msg.retain:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    parts = msg.topic.split("/")
    sn = parts[2] if len(parts) > 2 else msg.topic
    if serial_filter and serial_filter not in msg.topic:
        return
    live[sn] += 1
    first_seen.setdefault(sn, ts)
    last_seen[sn] = ts
    if len(samples[sn]) < 12:
        samples[sn].append(f"[{ts}] {msg.topic} => {msg.payload.decode('utf-8', 'replace')[:400]}")
    timeline.append(f"[{ts}] {msg.topic} => {msg.payload.decode('utf-8', 'replace')[:300]}")


cli = mqtt.Client(client_id=f"track-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, 1883, 30)
cli.loop_start()
print(f"tracking live messages for {seconds}s ...", flush=True)
while time.time() - t0 < seconds:
    time.sleep(1)
cli.loop_stop()
cli.disconnect()

lines = []
lines.append(f"=== LIVE publishers in {seconds}s (filter={serial_filter}) ===")
for sn, n in live.most_common():
    lines.append(f"{n:6d}  {sn}   first={first_seen[sn]} last={last_seen[sn]}")
    for s in samples[sn][:4]:
        lines.append("        " + s)
if not live:
    lines.append("(no live messages at all)")
lines.append("")
lines.append(f"=== TIMELINE ({len(timeline)} msgs) ===")
lines.extend(timeline)

text = "\n".join(lines)
with open("_tools/mqtt-track.txt", "w", encoding="utf-8") as fh:
    fh.write(text)
print(text[:6000])
