"""List retained discovery configs for one serial, after the prune ran."""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

SERIAL = (sys.argv[1] if len(sys.argv) > 1 else "9FF6").upper()
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0

found: dict[str, int] = {}


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/+/+/config", 1)
    client.subscribe("homeassistant/+/+/+/config", 1)


def on_message(client, userdata, msg):
    topic = msg.topic
    if SERIAL not in topic:
        return
    text = msg.payload.decode("utf-8", "replace")
    found[topic] = len(text)


client = mqtt.Client(client_id="cfg_after_%d" % int(time.time()))
client.username_pw_set("hm", "abc123456")
client.on_connect = on_connect
client.on_message = on_message
try:
    client.connect("192.168.31.99", 1883, 30)
except OSError:
    time.sleep(1)
    client.connect("192.168.31.99", 1883, 30)

client.loop_start()
time.sleep(WAIT)
client.loop_stop()
client.disconnect()

print("retained configs containing %s: %d" % (SERIAL, len(found)))
for topic in sorted(found):
    print("  %6d bytes  %s" % (found[topic], topic))
