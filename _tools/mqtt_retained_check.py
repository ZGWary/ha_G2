"""List the retained topics a device actually published, and flag the ones the
UI is accused of inventing.

Usage:  python mqtt_retained_check.py [SN_SUFFIX]

Retained messages are exactly the device's own statements: if a topic was never
published (or was published empty to clear it), it will not appear here.  That
makes this the ground truth for "does this device support this control".
"""

from __future__ import annotations

import json
import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

SN = sys.argv[1] if len(sys.argv) > 1 else "9FF6"

# The controls the user says must not be displayed over plain MQTT.
SUSPECTS = [
    "select/{d}/ems_mode/config",
    "select/{d}/ems_mode/command",
    "number/{d}/power_ctrl/config",
    "number/{d}/power_ctrl/set",
    "switch/{d}/set",
    "button/{d}/reboot/config",
    "button/{d}/reboot/trigger",
    "button/{d}/factory_reset/config",
    "button/{d}/factory_reset/trigger",
    "button/{d}/reset_ble_pin_code/config",
    "button/{d}/reset_ble_pin_code/trigger",
]

retained: dict[str, str] = {}
dev_ids: set[str] = set()


def on_connect(client, userdata, flags, rc):
    print(f"connect rc={rc}")
    client.subscribe("homeassistant/#", qos=0)


def on_message(client, userdata, msg):
    if not msg.retain:
        return
    topic = msg.topic
    payload = msg.payload.decode("utf-8", "replace")
    if payload == "":
        return
    retained[topic] = payload
    parts = topic.split("/")
    if len(parts) >= 3:
        dev_ids.add(parts[2])


client = mqtt.Client()
client.username_pw_set(USER, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, PORT, 30)
client.loop_start()
time.sleep(12)
client.loop_stop()
client.disconnect()

matching = sorted(d for d in dev_ids if SN.lower() in d.lower())
print(f"\nretained topics seen: {len(retained)}")
print(f"dev_ids matching {SN}: {matching}\n")

for dev in matching:
    print(f"=== {dev} ===")
    mine = sorted(t for t in retained if f"/{dev}/" in t)
    print(f"  total retained topics: {len(mine)}")
    for topic in mine:
        payload = retained[topic]
        short = payload if len(payload) <= 110 else payload[:110] + "..."
        print(f"    {topic}  ->  {short}")
    print("\n  -- suspect controls --")
    for pattern in SUSPECTS:
        topic = "homeassistant/" + pattern.format(d=dev)
        state = "PRESENT" if topic in retained else "absent "
        print(f"    [{state}] {topic}")
    print()

# Also report any retained topic mentioning these control names for any device,
# so a differently-named dev_id cannot hide the evidence.
print("=== any retained topic containing a suspect keyword ===")
for keyword in ("ems_mode", "power_ctrl", "reboot", "factory_reset", "reset_ble_pin_code"):
    hits = sorted(t for t in retained if keyword in t)
    print(f"  {keyword}: {len(hits)}")
    for h in hits:
        print(f"    {h}")
