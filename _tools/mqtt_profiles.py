"""Dump supported_topics for every device that declares them (read-only)."""
from __future__ import annotations

import json
import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PWD = "abc123456"

seen: dict[str, dict] = {}


def on_connect(cli, _u, _f, rc):
    print(f"connected rc={rc}", flush=True)
    cli.subscribe("homeassistant/sensor/+/attributes", 0)


def on_message(_c, _u, msg):
    dev = msg.topic.split("/")[2]
    try:
        payload = json.loads(msg.payload)
    except (ValueError, TypeError):
        return
    topics = payload.get("supported_topics")
    if isinstance(topics, dict):
        seen[dev] = topics


def main() -> None:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cli = mqtt.Client(client_id=f"prof-{int(time.time())}")
    cli.username_pw_set(USER, PWD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 60)
    cli.loop_start()
    time.sleep(seconds)
    cli.loop_stop()
    cli.disconnect()

    print(f"\n=== {len(seen)} device profile(s) ===", flush=True)
    for dev, topics in sorted(seen.items()):
        print(f"\n{dev}\n  {', '.join(sorted(topics))}", flush=True)


if __name__ == "__main__":
    main()
