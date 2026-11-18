"""Capture what a device announces on a FRESH connection.

Retained history is discarded - every retained message arrives in the first
seconds after subscribing, so the baseline is drawn after that.  From then on,
a delivery with retain=0 is a genuine live publish.

The reconnect is then located (a live ``/attributes`` republish, or a long gap
in ``quick/state``) and only what was published AFTER it is reported.  That is
exactly "the topics this connection announces".

Usage:  python mqtt_poweron_capture.py 9FF6 [seconds]
"""

from __future__ import annotations

import sys
import time

import paho.mqtt.client as mqtt

SERIAL = (sys.argv[1] if len(sys.argv) > 1 else "9FF6").upper()
CAPTURE_SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 420.0
BASELINE_SECONDS = 25.0
GAP_SECONDS = 25.0

PREFIXES = [f"RMI-{SERIAL}", f"MI-{SERIAL}"]

start = time.time()
baseline_set = False
events: list[tuple[float, str, bool]] = []


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=0)
    client.subscribe("hoymiles/#", qos=0)
    client.subscribe("hoymiles_g2/#", qos=0)


def on_message(client, userdata, msg):
    if SERIAL not in msg.topic.upper():
        return
    events.append((time.time() - start, msg.topic, bool(msg.retain)))


client = mqtt.Client()
client.username_pw_set("hm", "abc123456")
client.on_connect = on_connect
client.on_message = on_message
client.connect("192.168.31.99", 1883, 30)
client.loop_start()

print(f"capturing {CAPTURE_SECONDS:.0f}s for {SERIAL}", flush=True)
print(">>> POWER-CYCLE THE DEVICE NOW <<<\n", flush=True)

while True:
    time.sleep(1.0)
    elapsed = time.time() - start
    if not baseline_set and elapsed >= BASELINE_SECONDS:
        baseline_set = True
        retained = sum(1 for _, _, retain in events if retain)
        print(
            f"[{elapsed:6.1f}s] baseline drawn after {retained} retained messages.\n"
            f"          everything listed from here on is live.\n",
            flush=True,
        )
    if elapsed >= CAPTURE_SECONDS:
        break

client.loop_stop()
client.disconnect()

quick = [t for t, topic, retain in events if topic.endswith("/quick/state") and not retain]
attrs = [t for t, topic, retain in events if topic.endswith("/attributes") and not retain]

reconnect: float | None = None
if attrs:
    reconnect = min(attrs)
    print(f"reconnect: /attributes republished live at {reconnect:.1f}s")
else:
    for before, after in zip(quick, quick[1:]):
        if after - before > GAP_SECONDS:
            reconnect = after
            print(f"reconnect: quick/state silent {after - before:.0f}s, resumed {after:.1f}s")
            break

if reconnect is None:
    print("\nNO reconnect seen - the device never dropped and re-announced.")
    print("A capture without a power cycle says nothing about connect-time topics.")
    raise SystemExit(0)

counts: dict[str, int] = {}
for when, topic, retain in events:
    if when >= reconnect and not retain:
        counts[topic] = counts.get(topic, 0) + 1

print(f"\n== live topics published after the reconnect: {len(counts)} distinct")
for topic in sorted(counts):
    print(f"  {counts[topic]:>4}x  {topic}")

print("\n== reconnect burst in order (first 60 live messages)")
shown = 0
for when, topic, retain in events:
    if when < reconnect or retain:
        continue
    print(f"  +{when - reconnect:6.2f}s  {topic}")
    shown += 1
    if shown >= 60:
        print("  ...")
        break

for prefix in PREFIXES:
    hits = sum(n for t, n in counts.items() if prefix in t)
    print(f"\n== {prefix}: {hits} live messages after reconnect")
