"""Full MQTT topic dump - subscribes to '#' so nothing is missed."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"
seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 90
out = Path(__file__).with_name("mqtt-full.jsonl")

seen: dict[str, dict] = {}


def on_connect(c, u, flags, rc):
    print("connect rc", rc)
    c.subscribe("#", qos=0)


def on_message(c, u, msg):
    rec = {
        "topic": msg.topic,
        "retain": bool(msg.retain),
        "len": len(msg.payload),
        "payload": msg.payload.decode("utf-8", "replace"),
    }
    seen[msg.topic] = rec


cli = mqtt.Client(client_id=f"sniff-all-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, 1883, 30)
cli.loop_start()
time.sleep(seconds)
cli.loop_stop()
cli.disconnect()

with out.open("w", encoding="utf-8") as fh:
    for topic in sorted(seen):
        fh.write(json.dumps(seen[topic], ensure_ascii=False) + "\n")

print(f"=== {len(seen)} unique topics -> {out} ===")
