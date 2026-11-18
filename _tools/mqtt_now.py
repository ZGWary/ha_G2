"""Quick live (non-retained) topic census for one serial."""

from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

SERIAL = (sys.argv[1] if len(sys.argv) > 1 else "9FF6").upper()
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 40.0

baseline = False
start = time.time()
live: dict[str, int] = {}
retained: set[str] = set()


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=0)
    client.subscribe("hoymiles/#", qos=0)
    client.subscribe("hoymiles_g2/#", qos=0)


def on_message(client, userdata, msg):
    if SERIAL not in msg.topic.upper():
        return
    if msg.retain:
        retained.add(msg.topic)
        return
    if not baseline:
        return
    live[msg.topic] = live.get(msg.topic, 0) + 1


client = mqtt.Client()
client.username_pw_set("hm", "abc123456")
client.on_connect = on_connect
client.on_message = on_message
client.connect("192.168.31.99", 1883, 30)
client.loop_start()

time.sleep(8.0)
baseline = True
print(f"baseline set ({len(retained)} retained topics ignored); listening {SECONDS:.0f}s\n", flush=True)
time.sleep(SECONDS)
client.loop_stop()
client.disconnect()

print(f"== live publications now: {len(live)} distinct topics")
for topic in sorted(live):
    print(f"  {live[topic]:>4}x  {topic}")

print("\n== live /config topics")
cfgs = sorted(t for t in live if t.endswith("/config"))
if not cfgs:
    print("  NONE - the device is not re-announcing any discovery object")
for topic in cfgs:
    print(f"  {live[topic]:>4}x  {topic}")

print("\n== live command topics (/set, /command, /trigger)")
cmds = sorted(t for t in live if t.endswith(("/set", "/command", "/trigger")))
if not cmds:
    print("  NONE")
for topic in cmds:
    print(f"  {live[topic]:>4}x  {topic}")
