"""Check broker $SYS topics and whether a device SN is connected."""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"
seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 20

sys_seen: dict[str, str] = {}
other: list[str] = []


def on_connect(c, u, flags, rc):
    print("connect rc", rc)
    c.subscribe("$SYS/#", qos=0)


def on_message(c, u, msg):
    p = msg.payload.decode("utf-8", "replace")
    sys_seen[msg.topic] = p


cli = mqtt.Client(client_id=f"syscheck-{int(time.time())}", protocol=mqtt.MQTTv311)
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, 1883, 30)
cli.loop_start()
time.sleep(seconds)
cli.loop_stop()
cli.disconnect()

print(f"\n=== {len(sys_seen)} $SYS topics ===")
for t in sorted(sys_seen):
    print(f"{t} = {sys_seen[t]}")
