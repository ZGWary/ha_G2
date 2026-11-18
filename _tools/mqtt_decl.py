"""Print the live ``supported_topics`` declaration of given serials (read-only).

Usage:
    python mqtt_decl.py <SN> [<SN> ...]

Subscribes to ``homeassistant/sensor/<SN>/attributes`` for each serial, prints
the retained declaration, then compares it with the discovery objects that
exist for that serial so a missing topic is visible.  Never publishes.
"""
from __future__ import annotations

import json
import sys
import time

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

serials = sys.argv[1:]
if not serials:
    sys.exit(__doc__)

declared: dict[str, dict[str, str]] = {}
objects: dict[str, set[str]] = {sn: set() for sn in serials}
DISCOVERY = "homeassistant/#"


def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
    print(f"connected rc={rc}", flush=True)
    cli.subscribe(DISCOVERY, qos=1)


def on_message(_cli: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
    topic = msg.topic
    for sn in serials:
        if sn not in topic:
            continue
        if topic.endswith("/attributes"):
            try:
                payload = json.loads(msg.payload)
            except ValueError:
                return
            sup = payload.get("supported_topics")
            if isinstance(sup, dict):
                declared[sn] = sup
            return
        if topic.endswith("/config"):
            parts = topic.split("/")
            if len(parts) >= 4:
                objects[sn].add("/".join(parts[1:3]))


cli = mqtt.Client(client_id="decl-reader")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, PORT, 30)
cli.loop_start()
time.sleep(6)
cli.loop_stop()
cli.disconnect()

for sn in serials:
    decl = declared.get(sn, {})
    objs = objects.get(sn, set())
    print(f"\n===== {sn} =====")
    print("declared  : " + ", ".join(sorted(decl)) if decl else "declared  : <none>")
    print("discovery : " + ", ".join(sorted(objs)))
    print("declared but no discovery object: "
          + (", ".join(sorted(set(decl) - {o.split('/')[-1] for o in objs})) or "-"))
    print("discovery object but not declared: "
          + (", ".join(sorted({o.split('/')[-1] for o in objs} - set(decl))) or "-"))
