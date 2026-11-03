"""Which devices publish a phase_output_power discovery object (read-only)."""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PWD = "abc123456"

seen: set[str] = set()


def on_connect(cli, _u, _f, rc):
    print(f"connected rc={rc}", flush=True)
    cli.subscribe("homeassistant/number/+/phase_output_power/config", 0)


def on_message(_c, _u, msg):
    dev = msg.topic.split("/")[2]
    seen.add(dev)


def main() -> None:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cli = mqtt.Client(client_id=f"phase-{int(time.time())}")
    cli.username_pw_set(USER, PWD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 60)
    cli.loop_start()
    time.sleep(seconds)
    cli.loop_stop()
    cli.disconnect()

    print(f"\n=== {len(seen)} device(s) with phase_output_power ===", flush=True)
    for dev in sorted(seen):
        print(f"  {dev}", flush=True)


if __name__ == "__main__":
    main()
