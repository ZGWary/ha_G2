"""Inspect one MQTT topic: retained value, discovery config, and history (read-only).

Usage:
    python mqtt_topic.py <topic> [seconds]

Subscribes to the exact topic plus its `config` sibling, waits `seconds`
(default 5) to collect the retained payloads, then prints them verbatim.
Never publishes anything.
"""
from __future__ import annotations

import json
import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    topic = sys.argv[1]
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    targets = {topic, f"{topic}/config"}
    if topic.endswith("/set"):
        targets.add(topic[: -len("/set")] + "/config")

    found: dict[str, tuple[str, bool, int]] = {}

    def on_connect(cli: mqtt.Client, _ud: object, _flags: object, rc: int) -> None:
        print(f"connected rc={rc}")
        for t in sorted(targets):
            cli.subscribe(t, qos=1)
            print(f"  subscribe {t}")

    def on_message(_cli: mqtt.Client, _ud: object, msg: mqtt.MqttMessage) -> None:
        text = msg.payload.decode("utf-8", "replace")
        found[msg.topic] = (text, bool(msg.retain), msg.qos)

    cli = mqtt.Client(client_id=f"topic-{int(time.time())}")
    cli.username_pw_set(USER, PASSWORD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 30)
    cli.loop_start()
    time.sleep(seconds)
    cli.loop_stop()
    cli.disconnect()

    print(f"\n=== payloads seen on {topic} (+config) in {seconds}s ===")
    if not found:
        print("(none - no retained message, no live traffic)")
        return
    for t in sorted(found):
        text, retain, qos = found[t]
        print(f"\n--- {t}  retain={retain} qos={qos} len={len(text)}")
        try:
            print(json.dumps(json.loads(text), indent=2, ensure_ascii=False))
        except Exception:
            print(repr(text))


if __name__ == "__main__":
    main()
