"""List retained homeassistant/<domain>/<obj>/... config topics for one serial."""

from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

want = (sys.argv[1] if len(sys.argv) > 1 else "9FF6").upper()
retained: list[str] = []


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=0)


def on_message(client, userdata, msg):
    if msg.retain and msg.payload:
        retained.append(msg.topic)


client = mqtt.Client()
client.username_pw_set("hm", "abc123456")
client.on_connect = on_connect
client.on_message = on_message
client.connect("192.168.31.99", 1883, 30)
client.loop_start()
time.sleep(12)
client.loop_stop()
client.disconnect()

configs = [t for t in retained if want in t.upper() and t.endswith("/config")]
print(f"retained /*/config topics for {want}: {len(configs)}")
for topic in sorted(configs):
    print(f"  {topic}")

command_like = [
    t
    for t in retained
    if want in t.upper()
    and (
        t.endswith("/set")
        or t.endswith("/command")
        or t.endswith("/trigger")
    )
]
print(f"\nretained command-like topics for {want}: {len(command_like)}")
for topic in sorted(command_like):
    print(f"  {topic}")
