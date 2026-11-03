"""Watch one topic and report whether HA's number entity really publishes to it.

Usage:
    python mqtt_probe.py <topic> <seconds>

Read-only with respect to the device: it only subscribes.
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
    topic = sys.argv[1]
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
        print(f"connected rc={rc} listening on {topic}", flush=True)
        cli.subscribe(topic, qos=1)

    def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
        print(
            f"[{time.strftime('%H:%M:%S')}] {msg.topic} <= "
            f"{msg.payload.decode('utf-8', 'replace')!r} "
            f"qos={msg.qos} retain={msg.retain}",
            flush=True,
        )

    cli = mqtt.Client(client_id=f"probe-{int(time.time())}")
    cli.username_pw_set(USER, PASSWORD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 30)
    cli.loop_start()
    time.sleep(seconds)
    cli.loop_stop()
    cli.disconnect()
    print("done", flush=True)


if __name__ == "__main__":
    main()
