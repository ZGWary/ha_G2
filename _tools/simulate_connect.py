"""Replay a device's connect burst so the prune can be verified while it is off.

The firmware publishes a small, fixed set of discovery configs (and its
``attributes`` payload) the moment it links up.  When the unit is powered down we
cannot wait for that burst, so this reads the *retained* payloads the device left
behind and republishes exactly those topics with ``retain=0`` - which is
indistinguishable, to a subscriber, from the device connecting again.

Important: only topics the device is known to publish live are replayed.  Sending
a topic it does not publish would prove something false.

Usage:  python simulate_connect.py 9FF6 [held_seconds]
"""

from __future__ import annotations

import json
import sys
import time

import paho.mqtt.client as mqtt

SN = (sys.argv[1] if len(sys.argv) > 1 else "9FF6").upper()
# How long to stay connected after replaying, so the subscriber has time to
# finish its settle delay and act.
HOLD = int(sys.argv[2]) if len(sys.argv) > 2 else 45

HOST, PORT = "192.168.31.99", 1883
USER, PASSWORD = "hm", "abc123456"

# The exact configs observed in a power-cycle capture, plus the attributes
# payload.  Everything else the broker holds for this serial was never published
# live and must not be replayed.
#
# Note: ``switch/config`` is deliberately absent.  It looked live in an earlier
# capture only because this integration had republished it itself; the device's
# own connect burst does not include it.
LIVE_CONFIGS = (
    "homeassistant/number/{dev}/output_power/config",
)
LIVE_SENSORS = (
    "homeassistant/sensor/{dev}/attributes",
    "homeassistant/sensor/{dev}/quick/state",
    "homeassistant/sensor/{dev}/alarm/state",
    "homeassistant/sensor/{dev}/event/state",
)

retained: dict[str, bytes] = {}


def _targets() -> list[str]:
    dev = f"RMI-{SN}" if not SN.startswith("RMI-") else SN
    return [t.format(dev=dev) for t in (*LIVE_CONFIGS, *LIVE_SENSORS)]


WANTED = set(_targets())
# Only the payloads the device is known to always publish are mandatory; the
# state topics are replayed when the broker still has them.
REQUIRED = {
    t.format(dev=f"RMI-{SN}" if not SN.startswith("RMI-") else SN)
    for t in ("homeassistant/number/{dev}/output_power/config",
              "homeassistant/sensor/{dev}/attributes")
}


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=1)


def on_message(client, userdata, msg):
    if msg.retain and msg.payload and msg.topic in WANTED:
        retained[msg.topic] = msg.payload


client = mqtt.Client()
client.username_pw_set(USER, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, PORT, 30)
client.loop_start()
time.sleep(6)

missing = REQUIRED - set(retained)
if missing:
    print("MISSING retained payloads, cannot simulate faithfully:")
    for topic in sorted(missing):
        print(f"  {topic}")
    client.loop_stop()
    client.disconnect()
    sys.exit(1)

skipped = WANTED - set(retained)
for topic in sorted(skipped):
    print(f"  (not retained, skipping) {topic}")

print(f"replaying {len(retained)} live publishes for {SN}")
for topic in sorted(retained):
    info = client.publish(topic, retained[topic], qos=1, retain=False)
    info.wait_for_publish()
    print(f"  live -> {topic}")

print(f"holding {HOLD}s so the settle delay can elapse")
time.sleep(HOLD)
client.loop_stop()
client.disconnect()

print("\n-- attributes payload replayed --")
for topic in sorted(retained):
    if topic.endswith("/attributes"):
        try:
            payload = json.loads(retained[topic])
            keys = sorted(payload.get("supported_topics", {}))
            print(f"  supported_topics: {keys}")
        except (ValueError, TypeError):
            print(f"  (unparsable) {retained[topic]!r}")
