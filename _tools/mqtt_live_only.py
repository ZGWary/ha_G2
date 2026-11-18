"""Listen live (no retained) and report which topics the device publishes NOW."""

from __future__ import annotations

import time

import paho.mqtt.client as mqtt

LIVE: dict[str, int] = {}
start = time.time()


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=0)
    client.subscribe("hoymiles/#", qos=0)
    client.subscribe("hoymiles_g2/#", qos=0)


def on_message(client, userdata, msg):
    if msg.retain:
        return  # stale snapshot from the broker, not a live publication
    elapsed = time.time() - start
    LIVE.setdefault(msg.topic, 0)
    LIVE[msg.topic] += 1
    print(f"  +{elapsed:6.1f}s  {msg.topic}  {len(msg.payload)}B", flush=True)


client = mqtt.Client()
client.username_pw_set("hm", "abc123456")
client.on_connect = on_connect
client.on_message = on_message
client.connect("192.168.31.99", 1883, 30)
client.loop_start()
time.sleep(150)
client.loop_stop()
client.disconnect()

print(f"\n== live publications in {time.time() - start:.0f}s: {len(LIVE)} distinct topics")
for topic in sorted(LIVE):
    print(f"  {LIVE[topic]:>4}x  {topic}")

cfg = [t for t in LIVE if t.endswith("/config")]
print(f"\nlive /config publications: {len(cfg)}")
for topic in sorted(cfg):
    print(f"  {topic}")
