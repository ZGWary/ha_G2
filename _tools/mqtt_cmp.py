"""Compare two number command topics: retained payload presence + config (read-only)."""
from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

HOST = "192.168.31.99"
PORT = 1883
USER = "hm"
PASSWORD = "abc123456"


def main() -> None:
    devs = sys.argv[1:] or ["RMI-1650A028FC22", "MSA-280577777777"]
    topics = []
    for d in devs:
        topics += [
            f"homeassistant/number/{d}/power_ctrl/set",
            f"homeassistant/number/{d}/output_power/set",
            f"homeassistant/number/{d}/phase_output_power/set",
        ]

    found: dict[str, tuple[str, bool]] = {}

    def on_connect(cli: mqtt.Client, _u: object, _f: object, rc: int) -> None:
        print(f"connected rc={rc}")
        for t in topics:
            cli.subscribe(t, qos=1)

    def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MqttMessage) -> None:
        found[msg.topic] = (msg.payload.decode("utf-8", "replace"), bool(msg.retain))

    cli = mqtt.Client(client_id=f"cmp-{int(time.time())}")
    cli.username_pw_set(USER, PASSWORD)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(HOST, PORT, 30)
    cli.loop_start()
    time.sleep(6)
    cli.loop_stop()
    cli.disconnect()

    print("\n=== command topic payloads (retained only) ===")
    for t in topics:
        if t in found:
            payload, retain = found[t]
            print(f"  {t}\n      retain={retain} payload={payload!r}")
        else:
            print(f"  {t}\n      (NO retained payload)")

    print("\n=== devices having a phase_output_power discovery object ===")
    for d in devs:
        t = f"homeassistant/number/{d}/phase_output_power/config"
        cli2 = mqtt.Client(client_id=f"cmp2-{int(time.time()*1000)}")
        cli2.username_pw_set(USER, PASSWORD)
        got: dict[str, bool] = {}

        def _oc(c: mqtt.Client, _u: object, _f: object, rc: int, tt: str = t) -> None:
            c.subscribe(tt, qos=1)

        cli2.on_connect = _oc
        cli2.on_message = lambda c, u, m: got.__setitem__(m.topic, True)
        cli2.connect(HOST, PORT, 30)
        cli2.loop_start()
        time.sleep(2)
        cli2.loop_stop()
        cli2.disconnect()
        print(f"  {d}: {'yes' if got else 'NO'}")


if __name__ == "__main__":
    main()
