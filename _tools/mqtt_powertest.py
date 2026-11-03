"""Diagnose the FC22 (HiFlow micro inverter) output-power control path.

Subscribes to every topic of the device, optionally publishes one value to a
`/set` topic, and prints everything the device (or HA) sends back. Used to find
out whether `power_ctrl/set` and `output_power/set` are acknowledged at all.

Usage:
    python mqtt_powertest.py <SN> <topic-suffix> <payload> [seconds]
    python mqtt_powertest.py RMI-1650A028FC22 power_ctrl 200 40
    python mqtt_powertest.py RMI-1650A028FC22 output_power 300 40
    python mqtt_powertest.py RMI-1650A028FC22 --watch 40

Read-only unless a payload is given.
"""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"

INTERESTING = (
    "power_ctrl",
    "output_power",
    "quick/state",
    "device/state",
    "alarm/state",
    "attributes",
    "availability",
)

rows: list[tuple[float, str, str, bool]] = []


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)

    sn = sys.argv[1]
    watch = sys.argv[2] == "--watch"
    suffix = None if watch else sys.argv[2]
    payload = None if watch else sys.argv[3]
    seconds = int(sys.argv[3 if watch else 4]) if len(sys.argv) > (3 if watch else 4) else 40

    def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
        print(f"connected rc={rc}", flush=True)
        cli.subscribe("homeassistant/+/%s/#" % sn, qos=1)
        cli.subscribe("hoymiles_g2/%s/#" % sn, qos=1)
        cli.subscribe("+/%s/#" % sn, qos=1)
        cli.subscribe("%s/#" % sn, qos=1)

    def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
        text = msg.payload.decode("utf-8", "replace")
        rows.append((time.time(), msg.topic, text, bool(msg.retain)))
        if not any(k in msg.topic for k in INTERESTING):
            return
        short = text if len(text) < 300 else text[:300] + "..."
        print(
            f"[{time.strftime('%H:%M:%S')}] {msg.topic} <= {short!r} "
            f"retain={msg.retain} qos={msg.qos}",
            flush=True,
        )

    cli = mqtt.Client(client_id=f"powertest-{int(time.time())}")
    cli.username_pw_set(USER, PASSWORD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 30)
    cli.loop_start()

    time.sleep(8)  # collect retained discovery / state first

    if suffix:
        topic = f"homeassistant/number/{sn}/{suffix}/set"
        # An optional 5th argument turns this into a repeat test: the same value
        # is re-published every N seconds, which is how the card's timer works.
        every = int(sys.argv[5]) if len(sys.argv) > 5 else 0
        print(f"\n>>> publishing {payload!r} -> {topic}"
              + (f" every {every}s" if every else "") + "\n", flush=True)
        deadline = time.time() + seconds
        while time.time() < deadline:
            rows.append((time.time(), f"PUBLISH {topic}", payload, False))
            print(f"[{time.strftime('%H:%M:%S')}] --- publish {payload!r}", flush=True)
            cli.publish(topic, payload, qos=1)
            nap = every if every else seconds
            time.sleep(min(nap, max(0, deadline - time.time())))
    else:
        time.sleep(seconds)

    cli.loop_stop()
    cli.disconnect()
    print(f"\n=== total {len(rows)} messages ===", flush=True)


if __name__ == "__main__":
    main()
