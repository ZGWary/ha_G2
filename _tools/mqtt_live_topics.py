"""Report which state topics arrive for every device, with their retain flag.

Usage:
    python mqtt_live_topics.py [seconds]

Prints one line per topic template:
    <count>  <retain:yes/no>  <topic template>  <device>

Topics are the ``homeassistant/.../<name>/<sub>/state`` family plus the
``attributes`` inventory, which is what decides what the UI may show.
Read-only.
"""
from __future__ import annotations

import re
import sys
import time
from collections import defaultdict

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 45

SN = re.compile(r"((?:RMI|MSA)-[0-9A-Z]+)")

counts: dict[tuple[str, bool], set[str]] = defaultdict(set)
retained: set[str] = set()


def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
    print(f"connected rc={rc}", flush=True)
    cli.subscribe("homeassistant/#", qos=1)


def on_message(_cli: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
    topic = msg.topic
    if not (topic.endswith("/state") or topic.endswith("/attributes") or topic.endswith("/config")):
        return
    if topic.endswith("/config"):
        return
    match = SN.search(topic)
    dev = match.group(1) if match else "?"
    template = topic.replace(dev, "<SN>") if dev != "?" else topic
    counts[(template, bool(msg.retain))].add(dev)


cli = mqtt.Client(client_id="live-topics")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, PORT, 30)
cli.loop_start()
time.sleep(seconds)
cli.loop_stop()
cli.disconnect()

print()
for (template, retain), devs in sorted(counts.items()):
    print(f"{'R' if retain else ' '}  {template:62s}  {','.join(sorted(devs))}")
