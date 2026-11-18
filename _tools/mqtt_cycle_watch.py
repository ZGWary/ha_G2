"""Record, per device, which state topics arrive during a power cycle.

Usage:
    python mqtt_cycle_watch.py <seconds> <SN> [<SN> ...]

Prints a timestamped line the first time each topic is seen (so a reconnect
burst is visible as a repeated block after ``--- resubscribe ---``), and keeps a
running per-device topic set.  Read-only: never publishes, never uses retained
messages as evidence of activity (retained ones arrive once at subscribe time
and are marked as such).
"""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

seconds = float(sys.argv[1])
serials = sys.argv[2:]
if not serials:
    sys.exit(__doc__)

start = time.time()
first_seen: dict[str, set[str]] = {sn: set() for sn in serials}
retained_phase = True
counts: dict[str, int] = {sn: 0 for sn in serials}


def short(topic: str) -> str:
    parts = topic.split("/")
    if len(parts) >= 5:
        return "/".join(parts[2:-1])
    return topic


def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
    print(f"[{time.time() - start:6.1f}s] connected rc={rc}", flush=True)
    cli.subscribe("homeassistant/sensor/+/+/state", qos=0)
    cli.subscribe("homeassistant/sensor/+/state", qos=0)
    cli.subscribe("homeassistant/+/+/+/state", qos=0)


def on_message(_cli: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
    topic = msg.topic
    hit = None
    for sn in serials:
        if sn in topic:
            hit = sn
            break
    if hit is None:
        return
    counts[hit] += 1
    key = short(topic)
    fresh = key not in first_seen[hit]
    if fresh:
        first_seen[hit].add(key)
    tag = "retained" if msg.retain and retained_phase else ("NEW " if fresh else "    ")
    print(f"[{time.time() - start:6.1f}s] {hit} {tag} {key} = {msg.payload[:40]!r}", flush=True)


cli = mqtt.Client(client_id="cycle-watch")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, PORT, 30)
cli.loop_start()

# Retained copies all land within the first couple of seconds; after that every
# message is a live publish.
time.sleep(3.0)
retained_phase = False
print(f"[{time.time() - start:6.1f}s] --- live phase (retained replay done) ---", flush=True)

time.sleep(max(0.0, seconds - 3.0))
cli.loop_stop()
cli.disconnect()

print("\n=== topics seen per device ===", flush=True)
for sn in serials:
    print(f"{sn}: {len(first_seen[sn])} distinct topics, {counts[sn]} messages", flush=True)
    for key in sorted(first_seen[sn]):
        print(f"   {key}", flush=True)
