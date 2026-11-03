"""Read-only capture of every topic matching a serial (retained + live).

Usage: python mqtt_watch_sn.py <serial> <seconds>
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"
serial = sys.argv[1] if len(sys.argv) > 1 else "RMI-1650A028FC22"
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120

rows: list[str] = []
t0 = time.time()


def on_connect(c, u, flags, rc):
    print(f"connected rc={rc}", flush=True)
    c.subscribe("#", qos=0)


def on_message(c, u, msg):
    if serial not in msg.topic:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    body = msg.payload.decode("utf-8", "replace")
    rows.append(f"[{ts}] retain={msg.retain} qos={msg.qos} {msg.topic} => {body[:900]}")


cli = mqtt.Client(client_id=f"snwatch-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, 1883, 30)
cli.loop_start()
print(f"watching '{serial}' for {seconds}s", flush=True)
while time.time() - t0 < seconds:
    time.sleep(1)
cli.loop_stop()
cli.disconnect()

print(f"\n=== {len(rows)} message(s) matching {serial} in {seconds}s ===")
for r in rows:
    print(r)
