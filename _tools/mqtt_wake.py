"""Wake attempt for a Hoymiles device: set mqtt_ctrl mode + heartbeat.

Usage: python mqtt_track.py-style: python mqtt_wake.py <dev_id> <seconds>

Only ever writes to the given dev_id. Refuses MSA-* serials.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER = "192.168.31.99"
USER, PASSWORD = "hm", "abc123456"

dev = sys.argv[1] if len(sys.argv) > 1 else "RMI-1650A028FC22"
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120

if dev.startswith("MSA-"):
    sys.exit("REFUSED: MSA-* devices are read-only in this task")

hits: list[str] = []
t0 = time.time()
step = {"n": 0}


def on_connect(c, u, flags, rc):
    print(f"connected rc={rc}", flush=True)
    c.subscribe("#", qos=0)


def on_message(c, u, msg):
    if dev not in msg.topic:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    body = msg.payload.decode("utf-8", "replace")
    if msg.retain and msg.topic.endswith("/config"):
        hits.append(f"[{ts}] retain=True  {msg.topic}  (discovery config, {len(body)}B)")
        return
    hits.append(f"[{ts}] retain={msg.retain}  {msg.topic} => {body[:600]}")


cli = mqtt.Client(client_id=f"wake-{int(time.time())}")
cli.username_pw_set(USER, PASSWORD)
cli.on_connect = on_connect
cli.on_message = on_message
cli.connect(BROKER, 1883, 30)
cli.loop_start()
print(f"watching '{dev}' for {seconds}s", flush=True)
time.sleep(3)

plan = [
    (f"homeassistant/select/{dev}/ems_mode/command", "mqtt_ctrl"),
    (f"homeassistant/number/{dev}/power_ctrl/set", "200"),
    (f"homeassistant/number/{dev}/output_power/set", "800"),
]
for topic, payload in plan:
    info = cli.publish(topic, payload, qos=1, retain=False)
    info.wait_for_publish(timeout=10)
    print(f"  -> published {topic} = {payload} rc={info.rc}", flush=True)
    time.sleep(2)

# heartbeat: repeat power_ctrl every 20 s (protocol wants <= 1/min in mqtt_ctrl)
while time.time() - t0 < seconds:
    time.sleep(20)
    info = cli.publish(f"homeassistant/number/{dev}/power_ctrl/set", "200", qos=1, retain=False)
    info.wait_for_publish(timeout=10)
    print(f"  -> heartbeat power_ctrl=200 rc={info.rc} t={int(time.time()-t0)}s", flush=True)

cli.loop_stop()
cli.disconnect()

print(f"\n=== {len(hits)} message(s) matching {dev} in {seconds}s ===")
for h in hits:
    print(h)
