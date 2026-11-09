"""Data coordinator for the Hoymiles Micro Storage integration.

The firmware pushes state over MQTT; this coordinator subscribes to the topics
and fans the decoded JSON out to the entities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import mqtt_util
from .const import (
    AVAILABILITY_WATCHDOG_SECONDS,
    CAPABILITIES_ALL,
    DOMAIN,
    EMS_MODE_ECHO_GUARD_SECONDS,
    EMS_MODES,
    PAYLOAD_AVAILABLE,
    PAYLOAD_NOT_AVAILABLE,
    PHASE_POWER_MIN,
    PHASES,
    PV_COUNT_MAX,
    SOURCE_STALE_SECONDS,
    SRC_ALARM,
    SRC_DEVICE,
    SRC_KEEPALIVE,
    SRC_QUICK,
    SRC_SYSTEM,
    SRC_TOU_DAY_ACK,
    SRC_TOU_STATUS,
    SRC_TOU_WEEK_ACK,
    T_ALARM_STATE,
    T_ATTRIBUTES,
    T_AVAILABILITY,
    T_DEVICE_STATE,
    T_EMS_MODE_CMD,
    T_EMS_MODE_STATE,
    T_PHASE_OUTPUT_POWER_SET,
    T_QUICK_STATE,
    T_SYSTEM_STATE,
    T_TOU_DAY_ACK,
    T_TOU_STATUS,
    T_TOU_WEEK_ACK,
    model_from_dev_id,
    pv_count_from_dev_id,
)

_LOGGER = logging.getLogger(__name__)

# (coordinator data key, topic template, qos)
SUBSCRIPTIONS: tuple[tuple[str, str, int], ...] = (
    (SRC_QUICK, T_QUICK_STATE, 0),
    (SRC_DEVICE, T_DEVICE_STATE, 1),
    (SRC_SYSTEM, T_SYSTEM_STATE, 1),
    (SRC_ALARM, T_ALARM_STATE, 1),
    (SRC_TOU_STATUS, T_TOU_STATUS, 1),
    (SRC_TOU_DAY_ACK, T_TOU_DAY_ACK, 1),
    (SRC_TOU_WEEK_ACK, T_TOU_WEEK_ACK, 1),
)

# How long platform setup waits for the retained ``attributes`` payload that
# declares the device's capabilities.  It is retained, so it usually arrives
# within a few hundred milliseconds; the timeout only matters for a broker that
# lost it, in which case the full entity set is created (see CAPABILITIES_ALL).
CAPABILITIES_TIMEOUT_SECONDS: Final = 3.0


class HoymilesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Push-driven coordinator backed by MQTT subscriptions."""

    def __init__(self, hass: HomeAssistant, dev_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{dev_id}",
            update_interval=None,
        )
        self.dev_id = dev_id
        self.data = {}
        # Last commanded per phase output limit (protocol §15).  Populated from
        # the command topic itself, so values written by the firmware entity or
        # by any other client are picked up too.
        self.phase_output: dict[str, int] = {}
        # Last EMS mode we published, and when a command was issued.  Both drive
        # the state topic of the firmware's (otherwise optimistic) select.
        self._ems_mode_state: str | None = None
        self._ems_mode_command_time = 0.0
        self._unsubscribes: list[Any] = []
        self._last_seen: dict[str, float] = {}
        # None = no verdict yet.  Staying available until proven silent keeps a
        # Home Assistant restart from blanking out every entity instantly.
        self._available: bool | None = None
        # Capabilities declared by the firmware in its retained ``attributes``
        # payload.  ``None`` until that payload arrives, which the platforms
        # treat as "assume everything" so an upgrade never drops entities from a
        # device that merely had not been heard from yet.
        self._capabilities: frozenset[str] | None = None
        self._capabilities_ready = asyncio.Event()
        # Cached product name.  ``None`` = not resolved yet, ``""`` = resolved to
        # nothing (so the registry is not scanned again on every access).
        self._model: str | None = None

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """Return True unless the device was proven to have gone silent."""
        return self._available is not False

    @property
    def availability_topic(self) -> str:
        """Topic the patched discovery payloads subscribe to."""
        return mqtt_util.topic(T_AVAILABILITY, self.dev_id)

    @property
    def ems_mode(self) -> str | None:
        """Return the EMS mode the device is believed to be running.

        ``_ems_mode_state`` is what the select's state topic carries - the last
        commanded value, refined by whatever the device reports.  It is only
        ``None`` before the first command or report, which the keep-alive treats
        as "unknown, do not second guess" rather than "not mqtt_ctrl".
        """
        if self._ems_mode_state is not None:
            return self._ems_mode_state
        for source in (SRC_SYSTEM, SRC_DEVICE):
            payload = self.data.get(source)
            if not isinstance(payload, dict):
                continue
            mode = payload.get("ems_mode")
            if isinstance(mode, str) and mode:
                return mode
        return None

    # ------------------------------------------------------------------
    # capabilities
    # ------------------------------------------------------------------
    @property
    def capabilities(self) -> frozenset[str]:
        """Topics the firmware declared, or "all" while nothing was received."""
        return self._capabilities if self._capabilities is not None else CAPABILITIES_ALL

    @property
    def pv_count(self) -> int:
        """How many PV inputs this unit has.

        Three sources, most reliable first:

        1. The firmware's own ``device/state["pv_num"]`` - authoritative once a
           payload has arrived, because it describes the hardware directly.
        2. The SKU at the start of the serial (``RMI-4161`` -> 2 inputs).  Used
           before any payload exists, which is what matters during setup: the
           entities are created then, long before the first 5 minute report.
        3. ``PV_COUNT_MAX`` - the documented maximum, so a device that declares
           nothing still gets every port rather than silently losing readings.
        """
        payload = self.data.get(SRC_DEVICE)
        if isinstance(payload, dict):
            declared = payload.get("pv_num")
            if isinstance(declared, int) and not isinstance(declared, bool):
                if 1 <= declared <= PV_COUNT_MAX:
                    return declared

        known = pv_count_from_dev_id(self.dev_id)
        if known is not None:
            return known

        return PV_COUNT_MAX

    @property
    def device_model(self) -> str | None:
        """Product name for this unit, e.g. ``HiFlow Pro``.

        The firmware publishes its own MQTT discovery under the bare serial and
        that device registry entry carries a precise ``model``; this
        integration's own entry has none.  Reading it here lets every entity
        populate ``DeviceInfo.model`` from one place, which in turn means the
        dashboard title no longer depends on another integration being installed.

        Falls back to the serial prefix (``RMI-`` -> ``HiFlow``), then to
        ``None`` - a missing model only costs a less descriptive title.
        """
        if self._model is not None:
            return self._model or None

        resolved = ""
        try:
            from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

            registry = dr.async_get(self.hass)
        except Exception:  # noqa: BLE001 - a label is never worth breaking setup
            registry = None

        if registry is not None:
            # Every spelling the registry may use for this one serial: this
            # integration's ``(DOMAIN, "RMI-<SN>")`` and the firmware's
            # ``("mqtt", "<SN>")``.
            wanted = {
                self.dev_id.lower(),
                self.dev_id.lower().replace("-", ""),
            }
            if "-" in self.dev_id:
                wanted.add(self.dev_id.rsplit("-", 1)[-1].lower())

            for device in list(registry.devices.values()):
                for pair in device.identifiers:
                    if not pair or pair[1] is None:
                        continue
                    candidate = str(pair[1]).lower()
                    if candidate not in wanted and candidate.replace("-", "") not in wanted:
                        continue
                    for attr in ("model", "model_id"):
                        value = getattr(device, attr, None)
                        if value:
                            resolved = str(value)
                            break
                    if resolved:
                        break
                if resolved:
                    break

        if not resolved:
            resolved = model_from_dev_id(self.dev_id) or ""

        # Cached - including the empty result - because the registry is only read
        # during setup and a per-property lookup on every state write is wasteful.
        self._model = resolved
        return resolved or None

    def has_capability(self, capability: str) -> bool:
        """Return True when the firmware declared this capability."""
        return capability in self.capabilities

    @callback
    def set_keepalive_state(self, payload: dict[str, Any]) -> None:
        """Store the power-control keep-alive state for the entity.

        The keep-alive owns this data; pushing it through the coordinator means
        the sensor updates through the normal listener path instead of needing a
        subscription of its own.
        """
        data = dict(self.data)
        data[SRC_KEEPALIVE] = dict(payload)
        self.async_set_updated_data(data)

    @callback
    def add_capability(self, capability: str) -> None:
        """Record a capability discovered outside ``supported_topics``.

        The multi phase output limit has no ``supported_topics`` entry; all that
        exists is its own discovery object, which ``discovery_override.py``
        reports here.  Until it arrives the capability is simply absent, so a
        device that lacks the feature never gets the entities.
        """
        if self._capabilities is not None and capability in self._capabilities:
            return

        # Nothing received yet means "everything", so adding to that set would be
        # a no-op; only a real inventory needs extending.
        if self._capabilities is not None:
            self._capabilities = self._capabilities | {capability}
            _LOGGER.debug("Hoymiles %s gained capability %s", self.dev_id, capability)
            self.async_set_updated_data(dict(self.data))

    async def async_wait_for_capabilities(self) -> None:
        """Wait briefly for the retained ``attributes`` payload.

        The platforms need the capability set *before* they decide which
        entities to create, so setup awaits this instead of racing the MQTT
        message.  A timeout is not an error: it just means the broker has no
        retained inventory for this device and the full entity set is created.
        """
        if self._capabilities is not None:
            return
        try:
            await asyncio.wait_for(
                self._capabilities_ready.wait(), CAPABILITIES_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "No 'attributes' payload for %s within %ss; assuming a fully "
                "featured device",
                self.dev_id,
                CAPABILITIES_TIMEOUT_SECONDS,
            )

    @callback
    def _handle_attributes(self, msg: Any) -> None:
        """Record which topics the firmware says it implements.

        The payload is ``{"supported_topics": {"<cap>": "<topic>", ...}}``.  Only
        the keys matter: the values are topics we already know, and trusting
        them would let a firmware change point our subscriptions somewhere else.
        """
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.debug("Invalid JSON on %s: %s", msg.topic, msg.payload)
            return
        if not isinstance(payload, dict):
            return

        supported = payload.get("supported_topics")
        if not isinstance(supported, dict):
            return

        declared = frozenset(str(key) for key in supported)
        if declared == self._capabilities:
            return

        self._capabilities = declared
        self._capabilities_ready.set()
        _LOGGER.debug(
            "Hoymiles %s declares %s", self.dev_id, ", ".join(sorted(declared))
        )
        self.async_set_updated_data(dict(self.data))

    async def async_setup(self) -> None:
        """Subscribe to all device topics and start the availability watchdog."""
        for key, template, qos in SUBSCRIPTIONS:
            unsub = await mqtt_util.mqtt.async_subscribe(
                self.hass,
                mqtt_util.topic(template, self.dev_id),
                self._make_handler(key),
                qos,
            )
            self._unsubscribes.append(unsub)

        # The retained inventory of topics this firmware implements.  Subscribed
        # before anything else reads it, so platforms can gate on it.
        self._unsubscribes.append(
            await mqtt_util.mqtt.async_subscribe(
                self.hass,
                mqtt_util.topic(T_ATTRIBUTES, self.dev_id),
                self._handle_attributes,
                1,
            )
        )

        # Watching our own command topic lets the per phase numbers learn about
        # values produced elsewhere (firmware entity, scripts, ...).
        self._unsubscribes.append(
            await mqtt_util.mqtt.async_subscribe(
                self.hass,
                mqtt_util.topic(T_PHASE_OUTPUT_POWER_SET, self.dev_id),
                self._handle_phase_output,
                1,
            )
        )

        # Likewise for the EMS mode: the select's own state topic is fed from
        # here, so a command must be echoed no matter who sent it.
        self._unsubscribes.append(
            await mqtt_util.mqtt.async_subscribe(
                self.hass,
                mqtt_util.topic(T_EMS_MODE_CMD, self.dev_id),
                self._handle_ems_mode_command,
                1,
            )
        )

        self._unsubscribes.append(
            async_track_time_interval(
                self.hass,
                self._async_watchdog,
                timedelta(seconds=AVAILABILITY_WATCHDOG_SECONDS),
            )
        )

        # Mark the coordinator as healthy so CoordinatorEntity is available.
        self.async_set_updated_data(dict(self.data))

    async def async_shutdown(self) -> None:
        """Cancel all subscriptions and leave a usable retained state."""
        for unsub in self._unsubscribes:
            unsub()
        self._unsubscribes.clear()

        # The patched discovery payloads keep pointing at our availability topic
        # even after this entry is gone.  Publishing "online" while the device was
        # online leaves those entities usable instead of stranding them in
        # "unavailable" forever.
        if self._available:
            try:
                await mqtt_util.async_publish(
                    self.hass,
                    self.availability_topic,
                    PAYLOAD_AVAILABLE,
                    qos=1,
                    retain=True,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Unable to publish final availability", exc_info=True)

    # ------------------------------------------------------------------
    # multi phase output power (protocol §15)
    # ------------------------------------------------------------------
    @callback
    def _handle_phase_output(self, msg: Any) -> None:
        """Track the per phase limits published on the command topic."""
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return

        updated = False
        for phase in PHASES:
            value = payload.get(phase)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if self.phase_output.get(phase) != int(value):
                self.phase_output[phase] = int(value)
                updated = True

        if updated:
            self.async_set_updated_data(dict(self.data))

    @callback
    def restore_phase_output(self, phase: str, value: int) -> None:
        """Seed one phase from restored state (no MQTT traffic)."""
        if self.phase_output.get(phase) == value:
            return
        self.phase_output[phase] = value
        self.async_set_updated_data(dict(self.data))

    async def async_set_phase_output(self, phase: str, value: int) -> None:
        """Set one phase, keeping the other two at their last known value."""
        await self.async_set_phase_outputs({phase: value})

    async def async_set_phase_outputs(self, values: dict[str, int]) -> None:
        """Publish a complete phase output power command (protocol §15).

        The firmware rejects a partial payload, so every phase is always sent.
        """
        payload: dict[str, int] = {}
        unknown: list[str] = []

        for phase in PHASES:
            if phase in values:
                payload[phase] = int(values[phase])
                continue
            known = self.phase_output.get(phase)
            if known is None:
                unknown.append(phase)
                payload[phase] = PHASE_POWER_MIN
            else:
                payload[phase] = int(known)

        if unknown:
            _LOGGER.warning(
                "Phase output power: %s had no known value yet and defaults to %s W. "
                "Set all three phases, or use hoymiles_g2.set_phase_output_power, for "
                "full control.",
                ", ".join(unknown),
                PHASE_POWER_MIN,
            )

        await mqtt_util.async_publish(
            self.hass,
            mqtt_util.topic(T_PHASE_OUTPUT_POWER_SET, self.dev_id),
            payload,
        )

        # Optimistic update: the broker echo also lands in _handle_phase_output,
        # but this keeps the UI responsive when the echo is delayed.
        self.phase_output.update(payload)
        self.async_set_updated_data(dict(self.data))

    # ------------------------------------------------------------------
    # EMS mode select state (protocol §3 / §12)
    # ------------------------------------------------------------------
    @callback
    def _handle_ems_mode_command(self, msg: Any) -> None:
        """Echo a commanded EMS mode onto the select's state topic."""
        mode = mqtt_util.payload_to_text(msg.payload)
        if mode is None:
            return

        mode = mode.strip('"')
        if mode not in EMS_MODES:
            return

        self._ems_mode_command_time = time.monotonic()
        if mode == self._ems_mode_state:
            return

        self.hass.async_create_task(self._async_publish_ems_mode_state(mode))

    async def _async_sync_ems_mode_state(self, mode: str) -> None:
        """Follow the mode the device actually reports in system/state."""
        if mode not in EMS_MODES or mode == self._ems_mode_state:
            return

        # A ``system/state`` tick landing right after a command can still carry
        # the previous mode; waiting for the next one avoids a flip back.
        if (
            time.monotonic() - self._ems_mode_command_time
        ) < EMS_MODE_ECHO_GUARD_SECONDS:
            return

        await self._async_publish_ems_mode_state(mode)

    async def _async_publish_ems_mode_state(self, mode: str) -> None:
        """Publish the EMS mode, retained so it survives a HA restart."""
        self._ems_mode_state = mode
        try:
            await mqtt_util.async_publish(
                self.hass,
                mqtt_util.topic(T_EMS_MODE_STATE, self.dev_id),
                mode,
                qos=1,
                retain=True,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Unable to publish the EMS mode state", exc_info=True)

    # ------------------------------------------------------------------
    # availability internals
    # ------------------------------------------------------------------
    async def _async_watchdog(self, _now: Any = None) -> None:
        """Mark the device unavailable once every source went stale."""
        if self._evaluate_availability() is False and self._available is not False:
            await self._async_publish_availability(False)

    @callback
    def _evaluate_availability(self) -> bool | None:
        """Return True/False, or None when nothing can be concluded yet."""
        now = time.monotonic()

        for source, window in SOURCE_STALE_SECONDS.items():
            last_seen = self._last_seen.get(source)
            if last_seen is not None and (now - last_seen) <= window:
                return True

        # Never seen anything at all: leave the retained value alone instead of
        # declaring a healthy device offline right after Home Assistant started.
        if not self._last_seen:
            return None

        return False

    async def _async_publish_availability(self, available: bool) -> None:
        """Publish an availability change and refresh the entities."""
        self._available = available
        payload = PAYLOAD_AVAILABLE if available else PAYLOAD_NOT_AVAILABLE

        try:
            await mqtt_util.async_publish(
                self.hass, self.availability_topic, payload, qos=1, retain=True
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Unable to publish availability", exc_info=True)
            return

        _LOGGER.info("Hoymiles %s is now %s", self.dev_id, payload)
        self.async_set_updated_data(dict(self.data))

    # ------------------------------------------------------------------
    # state topics
    # ------------------------------------------------------------------
    @callback
    def _make_handler(self, key: str):
        @callback
        def _handler(msg: Any) -> None:
            try:
                payload = json.loads(msg.payload)
            except (ValueError, TypeError):
                _LOGGER.debug("Invalid JSON on %s: %s", msg.topic, msg.payload)
                return
            if not isinstance(payload, dict):
                return

            if key in SOURCE_STALE_SECONDS:
                self._last_seen[key] = time.monotonic()

            data = dict(self.data)
            data[key] = payload
            self.async_set_updated_data(data)

            # A fresh message can only ever flip the verdict to available; the
            # watchdog is responsible for the opposite direction.
            if key in SOURCE_STALE_SECONDS and self._available is not True:
                self.hass.async_create_task(self._async_publish_availability(True))

            # Both report carriers can carry the running EMS mode: a storage
            # unit puts it in ``system/state``, a micro inverter (which has no
            # ``system/state`` at all) puts it in ``device/state``.
            if key in (SRC_SYSTEM, SRC_DEVICE):
                mode = payload.get("ems_mode")
                if isinstance(mode, str):
                    self.hass.async_create_task(self._async_sync_ems_mode_state(mode))

        return _handler
