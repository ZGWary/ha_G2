"""Publish a single command to one device topic.

Usage: python mqtt_pub.py <topic> <payload>

Safety: refuses to touch any MSA- serial (read-only reference devices).
"""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"

topic = sys.argv[1]
payload = sys.argv[2]

if "MSA-" in topic:
    sys.exit("REFUSED: MSA-* devices are read-only in this task")

cli = mqtt.Client(client_id=f"pub-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.connect(BROKER, 1883, 30)
info = cli.publish(topic, payload, qos=1, retain=False)
info.wait_for_publish(timeout=10)
print(f"published topic={topic} payload={payload} rc={info.rc} retain=False qos=1")
cli.disconnect()
