"""Which capability keys appear in ANY device's supported_topics inventory."""

from __future__ import annotations

import json
import time

import paho.mqtt.client as mqtt

retained: dict[str, str] = {}


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=0)


def on_message(client, userdata, msg):
    if msg.retain and msg.payload:
        retained[msg.topic] = msg.payload.decode("utf-8", "replace")


client = mqtt.Client()
client.username_pw_set("hm", "abc123456")
client.on_connect = on_connect
client.on_message = on_message
client.connect("192.168.31.99", 1883, 30)
client.loop_start()
time.sleep(12)
client.loop_stop()
client.disconnect()

seen: dict[str, int] = {}
inventories = 0
for topic, raw in retained.items():
    if not topic.endswith("/attributes"):
        continue
    try:
        data = json.loads(raw)
    except Exception:
        continue
    supported = data.get("supported_topics")
    if not isinstance(supported, dict):
        continue
    inventories += 1
    for key in supported:
        seen[key] = seen.get(key, 0) + 1

print(f"inventories read: {inventories}\n")
print("key                        devices declaring it")
for key, count in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0])):
    print(f"  {key:<24} {count}")

print("\nnever declared by any device:")
for key in (
    "factory_reset",
    "reset_ble_pin_code",
    "switch_ctrl",
    "reboot",
    "ems_mode",
    "power_ctrl",
    "output_power",
    "phase_output_power",
):
    if key not in seen:
        print(f"  {key}")
