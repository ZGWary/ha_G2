"""Dump the full retained payload of the control discovery topics for one device."""

from __future__ import annotations

import json
import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

DEV = sys.argv[1] if len(sys.argv) > 1 else "RMI-4161A0209FF6"

WANTED = [
    f"homeassistant/select/{DEV}/ems_mode/config",
    f"homeassistant/number/{DEV}/power_ctrl/config",
    f"homeassistant/number/{DEV}/output_power/config",
    f"homeassistant/switch/{DEV}/config",
    f"homeassistant/button/{DEV}/reboot/config",
    f"homeassistant/button/{DEV}/factory_reset/config",
    f"homeassistant/button/{DEV}/reset_ble_pin_code/config",
    f"homeassistant/sensor/{DEV}/attributes",
]

retained: dict[str, str] = {}


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=0)


def on_message(client, userdata, msg):
    if msg.retain and msg.payload:
        retained[msg.topic] = msg.payload.decode("utf-8", "replace")


client = mqtt.Client()
client.username_pw_set(USER, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, PORT, 30)
client.loop_start()
time.sleep(10)
client.loop_stop()
client.disconnect()

for topic in WANTED:
    payload = retained.get(topic)
    print(f"--- {topic}")
    if payload is None:
        print("    (no retained message)")
        continue
    try:
        print(json.dumps(json.loads(payload), indent=2, ensure_ascii=False))
    except Exception:
        print(payload)
    print()

# Every retained topic for this dev, one per line, so nothing is missed.
print(f"--- all retained topics for {DEV}")
for topic in sorted(t for t in retained if t.split("/")[2:3] == [DEV]):
    print(f"    {topic}")
