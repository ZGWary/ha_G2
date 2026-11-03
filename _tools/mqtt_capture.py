"""Capture the full FC22 telemetry cycle into a file (unbuffered, read-only).

Usage:
    python mqtt_capture.py <dev_id> <seconds> <outfile>

Subscribes to `homeassistant/sensor/<dev>/#` and logs every non quick/state
message with a timestamp so the 5 minute `device/state` cadence can be measured.
Writes progress immediately (flush) so a tail can follow it.
"""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"


def main() -> None:
    dev = sys.argv[1]
    seconds = int(sys.argv[2])
    out = sys.argv[3]
    wildcard = f"homeassistant/sensor/{dev}/#"
    fh = open(out, "w", encoding="utf-8")

    def log(line: str) -> None:
        fh.write(line + "\n")
        fh.flush()

    seen: dict[str, int] = {}

    def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
        log(f"connected rc={rc} {wildcard}")
        cli.subscribe(wildcard, qos=1)

    def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
        leaf = msg.topic.split("/", 3)[-1]
        seen[leaf] = seen.get(leaf, 0) + 1
        if leaf == "quick/state":
            return
        payload = msg.payload.decode("utf-8", "replace")
        log(f"[{time.strftime('%H:%M:%S')}] {leaf} retain={msg.retain} {payload}")

    cli = mqtt.Client(client_id=f"cap-{int(time.time())}")
    cli.username_pw_set(USER, PASSWORD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 30)
    cli.loop_start()
    time.sleep(seconds)
    cli.loop_stop()
    cli.disconnect()

    log("\n=== counts ===")
    for leaf, n in sorted(seen.items()):
        log(f"{leaf}: {n}")
    fh.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
