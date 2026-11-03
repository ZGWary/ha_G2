"""List live (non-retained) publishers seen in a time window."""
from __future__ import annotations

import sys
import time
from collections import Counter

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"
seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 30

live: Counter[str] = Counter()
retained: Counter[str] = Counter()
samples: dict[str, str] = {}


def on_connect(c, u, flags, rc):
    c.subscribe("#", qos=0)


def on_message(c, u, msg):
    parts = msg.topic.split("/")
    sn = parts[2] if len(parts) > 2 else msg.topic
    if msg.retain:
        retained[sn] += 1
    else:
        live[sn] += 1
        samples.setdefault(sn, msg.topic + " => " + msg.payload.decode("utf-8", "replace")[:120])


cli = mqtt.Client(client_id=f"live-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, 1883, 30)
cli.loop_start()
time.sleep(seconds)
cli.loop_stop()
cli.disconnect()

print(f"\n=== LIVE (non-retained) publishers in {seconds}s ===")
for sn, n in live.most_common():
    print(f"{n:5d}  {sn}")
    print(f"        sample: {samples.get(sn)}")

print(f"\n=== RETAINED counts ===")
for sn, n in retained.most_common(20):
    print(f"{n:5d}  {sn}")
