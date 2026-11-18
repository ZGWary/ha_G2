"""Watch live (retain=False) discovery publishes for a while.

Usage: python g2_live_watch.py [seconds]
"""
import sys
import time

import paho.mqtt.client as mqtt

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 50.0
seen = {}


def on_msg(client, userdata, msg):
    if getattr(msg, "retain", True) is False:
        seen[msg.topic] = seen.get(msg.topic, 0) + 1
        print("LIVE", msg.topic, flush=True)


client = mqtt.Client()
client.username_pw_set("hm", "abc123456")
client.on_message = on_msg
client.connect("192.168.31.99", 1883, 30)
client.subscribe("homeassistant/#", 1)
client.loop_start()
time.sleep(SECONDS)
client.loop_stop()
client.disconnect()

print("--- live discovery topics:", len(seen))
for topic in sorted(seen):
    print("   ", seen[topic], "x", topic)
