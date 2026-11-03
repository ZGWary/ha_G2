"""Sniff MQTT traffic for a given device so we can compare 7777 vs FC22 payloads.

Usage:
    python mqtt_sniff.py <SN> [seconds]

Writes every message to a JSONL file next to this script and prints a summary.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

sn = sys.argv[1]
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 90
out = Path(__file__).with_name(f"mqtt-{sn}.jsonl")

messages: list[dict] = []


def on_connect(c, u, flags, rc):
    print("connect rc", rc)
    c.subscribe("homeassistant/#", qos=0)
    c.subscribe("hoymiles_g2/#", qos=0)
    c.subscribe("+/+/#", qos=0)


def on_message(c, u, msg):
    payload = msg.payload.decode("utf-8", "replace")
    rec = {"t": round(time.time(), 3), "topic": msg.topic, "payload": payload}
    messages.append(rec)
    print(json.dumps(rec, ensure_ascii=False)[:400])


cli = mqtt.Client(client_id=f"sniff-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, PORT, 30)
cli.loop_start()
time.sleep(seconds)
cli.loop_stop()
cli.disconnect()

with out.open("w", encoding="utf-8") as fh:
    for rec in messages:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"\n=== {len(messages)} messages -> {out} ===")
