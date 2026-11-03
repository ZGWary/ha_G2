"""Track broker client count and live publishers together."""
from __future__ import annotations

import sys
import time
from collections import Counter

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"
seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 40

live: Counter[str] = Counter()
sysvals: dict[str, str] = {}


def on_connect(c, u, flags, rc):
    c.subscribe("#", qos=0)
    c.subscribe("$SYS/broker/clients/#", qos=0)
    c.subscribe("$SYS/broker/connections/#", qos=0)


def on_message(c, u, msg):
    if msg.topic.startswith("$SYS/"):
        sysvals[msg.topic] = msg.payload.decode()
        return
    if msg.retain:
        return
    parts = msg.topic.split("/")
    sn = parts[2] if len(parts) > 2 else msg.topic
    live[sn] += 1


cli = mqtt.Client(client_id=f"track-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, 1883, 30)
cli.loop_start()
time.sleep(seconds)
cli.loop_stop()
cli.disconnect()

print("=== broker client stats ===")
for k in sorted(sysvals):
    print(f"{k} = {sysvals[k]}")
print(f"\n=== live publishers ({seconds}s) ===")
for sn, n in live.most_common():
    print(f"{n:5d}  {sn}")
if not live:
    print("(none)")
