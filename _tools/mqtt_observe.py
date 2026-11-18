"""List which topics a device actually publishes (read-only).

Usage:
    python mqtt_observe.py <SN> [seconds]

Subscribes to every topic below the device's serial and prints the topic
template plus the number of messages seen, so the declaration in
``attributes`` can be compared with what is really arriving.
Never publishes anything.
"""
from __future__ import annotations

import sys
import time
from collections import Counter

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

sn = sys.argv[1]
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 45

counts: Counter[str] = Counter()
first: dict[str, float] = {}
start = time.time()


def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
    print(f"connected rc={rc}", flush=True)
    cli.subscribe("#", qos=1)


def on_message(_cli: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
    if sn not in msg.topic:
        return
    key = msg.topic.replace(sn, "<SN>")
    counts[key] += 1
    first.setdefault(key, round(msg.timestamp - start, 1) if hasattr(msg, "timestamp") else 0)


cli = mqtt.Client(client_id=f"observe-{sn[-4:]}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, PORT, 30)
cli.loop_start()
deadline = time.time() + seconds
while time.time() < deadline:
    time.sleep(1)
cli.loop_stop()
cli.disconnect()

print(f"\n--- {sn}: {sum(counts.values())} messages in {seconds}s ---")
for topic, n in sorted(counts.items()):
    print(f"{n:5d}  {topic}")
