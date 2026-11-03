"""List every device id that appears on the broker, retained + live (read-only).

Usage:
    python mqtt_devs.py [seconds]

Subscribes '#' with qos=1, collects for `seconds` (default 25), then prints a
summary of the second topic level for `homeassistant/...` and the first topic
level for everything else.  Never publishes.
"""
from __future__ import annotations

import re
import sys
import time
from collections import Counter, defaultdict

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

SERIAL_RE = re.compile(r"^(MSA|RMI|HMS|HMT|DTU)-[0-9A-Za-z]+$|^[0-9A-Za-z]{10,16}$")


def main() -> None:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    per_dev: dict[str, set[str]] = defaultdict(set)

    def on_connect(cli: mqtt.Client, _ud: object, _flags: object, rc: int) -> None:
        print(f"connected rc={rc}")
        cli.subscribe("#", qos=1)

    def on_message(_cli: mqtt.Client, _ud: object, msg: mqtt.MqttMessage) -> None:
        topic = msg.topic
        parts = topic.split("/")
        if parts[0] == "homeassistant" and len(parts) >= 3:
            cand = parts[2]
        elif len(parts) >= 2:
            cand = parts[1]
        else:
            cand = parts[0]
        counts[cand] += 1
        if SERIAL_RE.match(cand):
            seen.add(cand)
            per_dev[cand].add("/".join(parts[3:]) if parts[0] == "homeassistant" else "/".join(parts[2:]))

    cli = mqtt.Client(client_id=f"devs-{int(time.time())}")
    cli.username_pw_set(USER, PASSWORD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 30)
    cli.loop_start()
    time.sleep(seconds)
    cli.loop_stop()
    cli.disconnect()

    print(f"\n=== device-like ids in {seconds}s ===")
    for dev in sorted(seen):
        print(f"{dev:24s} msgs={counts[dev]:5d}  leaves={sorted(per_dev[dev])}")

    print("\n=== top-level buckets ===")
    for name, n in counts.most_common(30):
        print(f"{name:32s} {n}")


if __name__ == "__main__":
    main()
