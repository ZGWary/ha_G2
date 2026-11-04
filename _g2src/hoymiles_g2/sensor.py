"""Sensor entities for the Hoymiles Micro Storage integration.

These entities reproduce the state fields the firmware pushes on
``quick/state`` (1 s, all roles), ``device/state`` (5 min, all roles) and
``system/state`` (5 min, master/single only) plus the TOU ack/status topics.

``soc`` and ``bat_power`` are intentionally *not* re-created here because the
firmware already registers them through MQTT discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CAP_ALARM_STATE,
    CAP_DEVICE_STATE,
    CAP_QUICK_STATE,
    CAP_SYSTEM_STATE,
    CAP_TOU,
    DOMAIN,
    MANUFACTURER,
    SRC_DEVICE,
    SRC_KEEPALIVE,
    SRC_QUICK,
    SRC_SYSTEM,
    SRC_TOU_DAY_ACK,
    SRC_TOU_STATUS,
    SRC_TOU_WEEK_ACK,
    TOU_DAY_ACK_STATUS,
    TOU_GET_STATUS,
    TOU_WEEK_ACK_STATUS,
)
from .coordinator import HoymilesCoordinator

# ---------------------------------------------------------------------------
# value_fn helpers
# ---------------------------------------------------------------------------


def _payload(data: dict[str, Any], source: str) -> dict[str, Any]:
    value = data.get(source)
    return value if isinstance(value, dict) else {}


def q(field: str, default: Any = None) -> Callable[[dict], Any]:
    """Read a top level field from quick/state."""

    def _fn(data: dict[str, Any]) -> Any:
        return _payload(data, SRC_QUICK).get(field, default)

    return _fn


def d(field: str, default: Any = None) -> Callable[[dict], Any]:
    """Read a top level field from device/state."""

    def _fn(data: dict[str, Any]) -> Any:
        return _payload(data, SRC_DEVICE).get(field, default)

    return _fn


def s(field: str, default: Any = None) -> Callable[[dict], Any]:
    """Read a top level field from system/state."""

    def _fn(data: dict[str, Any]) -> Any:
        return _payload(data, SRC_SYSTEM).get(field, default)

    return _fn


# Documented order of the ``grid`` array in device/state (protocol §23).
GRID_TYPES: Final = ("grid_on", "grid_off", "inv")


def grid(index: int, field: str, default: Any = None) -> Callable[[dict], Any]:
    """Read ``grid[index].<field>`` from device/state (0=on, 1=off, 2=inv).

    Entries are matched by their ``type`` field instead of by position, so the
    energy dashboard and the statistics built on these sensors keep working even
    if the firmware ever reorders or filters the array.  The documented order is
    only used as a fallback for entries without a ``type``.
    """

    def _fn(data: dict[str, Any]) -> Any:
        items = _payload(data, SRC_DEVICE).get("grid")
        if not isinstance(items, list):
            return default

        wanted = GRID_TYPES[index] if 0 <= index < len(GRID_TYPES) else None
        if wanted is not None:
            for item in items:
                if isinstance(item, dict) and item.get("type") == wanted:
                    return item.get(field, default)

        if len(items) > index and isinstance(items[index], dict):
            return items[index].get(field, default)

        return default

    return _fn


def _pv_entry(data: dict[str, Any], index: int) -> dict[str, Any] | None:
    """Return the ``pvs[]`` entry for port ``index`` (0-based), if present.

    Ports are matched by ``id`` (1-based in the protocol) and only fall back to
    the array position, so a missing entry cannot shift the value of every
    following port.
    """
    items = _payload(data, SRC_DEVICE).get("pvs")
    if not isinstance(items, list):
        return None

    for item in items:
        if isinstance(item, dict) and item.get("id") == index + 1:
            return item

    if len(items) > index and isinstance(items[index], dict):
        return items[index]

    return None


def pv(index: int, default: Any = None) -> Callable[[dict], Any]:
    """Read the power of PV port ``index`` (0-based) from device/state."""

    def _fn(data: dict[str, Any]) -> Any:
        entry = _pv_entry(data, index)
        return default if entry is None else entry.get("p", default)

    return _fn


def pv_energy(index: int, field: str, default: Any = None) -> Callable[[dict], Any]:
    """Read an energy counter of PV port ``index`` from device/state.

    A micro inverter reports the per port energy as ``ed`` (today) and ``et``
    (lifetime) inside ``pvs[]``; a storage unit leaves both out and reports the
    equivalent totals in ``system/state`` instead.  This is therefore the only
    source of a PV energy figure on a model without ``system_state``.
    """

    def _fn(data: dict[str, Any]) -> Any:
        entry = _pv_entry(data, index)
        return default if entry is None else entry.get(field, default)

    return _fn


def _pv_energy_sum(data: dict[str, Any], field: str) -> Any:
    """Sum an energy counter over every ``pvs[]`` entry, ``None`` when absent.

    The port count varies per model (a HiFlow micro inverter typically has two),
    so the total is summed over whatever the payload actually contains rather
    than over a fixed number of ports.  An entry that omits the field simply does
    not contribute, and a payload with no usable entry yields ``None`` so the
    sensor stays ``unknown`` instead of reporting a misleading ``0``.
    """
    items = _payload(data, SRC_DEVICE).get("pvs")
    if not isinstance(items, list):
        return None

    total = 0
    seen = False
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        total += value
        seen = True

    return total if seen else None


def pv_energy_total(field: str, default: Any = None) -> Callable[[dict], Any]:
    """Sum an energy counter of every PV port from device/state."""

    def _fn(data: dict[str, Any]) -> Any:
        total = _pv_energy_sum(data, field)
        return default if total is None else total

    return _fn


def s_or_pv(field: str, pv_field: str) -> Callable[[dict], Any]:
    """Read a field from system/state, falling back to the ``pvs[]`` sum.

    A storage unit reports its daily PV energy as ``pv_e`` in ``system/state``;
    a micro inverter has no such topic at all and instead publishes ``ed`` (today)
    per port.  Reading both keeps one entity meaningful on either model rather
    than leaving it ``unknown`` on the model that lacks the topic.
    """

    def _fn(data: dict[str, Any]) -> Any:
        value = _payload(data, SRC_SYSTEM).get(field)
        if value is not None:
            return value
        return _pv_energy_sum(data, pv_field)

    return _fn


def pack(index: int, field: str, default: Any = None) -> Callable[[dict], Any]:
    """Read ``packs[index].<field>`` from device/state (0-based).

    Packs are matched by ``id`` (1-based in the protocol), so a missing pack
    cannot shift the values of the remaining ones.
    """

    def _fn(data: dict[str, Any]) -> Any:
        items = _payload(data, SRC_DEVICE).get("packs")
        if not isinstance(items, list):
            return default

        for item in items:
            if isinstance(item, dict) and item.get("id") == index + 1:
                return item.get(field, default)

        if len(items) > index and isinstance(items[index], dict):
            return items[index].get(field, default)

        return default

    return _fn


def _ack(source: str, table: dict[int, str]):
    """Build a value_fn for an ack/status topic (returns a readable string)."""

    def _fn(data: dict[str, Any]) -> str | None:
        payload = _payload(data, source)
        status = payload.get("status")
        if status is None:
            return None
        try:
            code = int(status)
        except (TypeError, ValueError):
            return str(status)
        text = table.get(code, "unknown")
        return f"{code} - {text}"

    return _fn


def _ems_mode_value(data: dict[str, Any]) -> Any:
    """Read the running EMS mode from whichever report carrier has it.

    A storage unit publishes ``system/state`` and puts ``ems_mode`` there; a
    micro inverter has no ``system/state`` at all and reports the same field
    inside ``device/state``.  Reading only one of them leaves half the supported
    models stuck at "unknown", so both are consulted - ``system/state`` wins
    because it is the master role's authoritative view.
    """
    for source in (SRC_SYSTEM, SRC_DEVICE):
        value = _payload(data, source).get("ems_mode")
        if isinstance(value, str) and value:
            return value
    return None


def _tou_status_value(data: dict[str, Any]) -> str | None:
    payload = _payload(data, SRC_TOU_STATUS)
    status = payload.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return str(status)
    week = payload.get("week")
    day_idx = payload.get("day_idx")
    text = TOU_GET_STATUS.get(code, "unknown")
    if code == 0 and week is not None:
        return f"{week} day{day_idx} - {text}"
    return f"{code} - {text}"


def _keepalive_value(data: dict[str, Any]) -> str:
    """Return the keep-alive's running state as a readable string."""
    payload = _payload(data, SRC_KEEPALIVE)
    if not payload:
        return "off"
    if payload.get("enabled") is True:
        return "on"
    if payload.get("error"):
        return "error"
    return "off"


def _keepalive_attrs(data: dict[str, Any]) -> dict[str, Any]:
    """Expose the full keep-alive payload, which is what the card reads."""
    return _payload(data, SRC_KEEPALIVE)


def _tou_attrs(source: str) -> Callable[[dict], dict[str, Any]]:
    def _fn(data: dict[str, Any]) -> dict[str, Any]:
        payload = _payload(data, source)
        attrs: dict[str, Any] = {}
        if payload.get("status") is not None:
            attrs["status"] = payload["status"]
        if payload.get("err_msg") is not None:
            attrs["err_msg"] = payload["err_msg"]
        if isinstance(payload.get("day_plan"), list):
            attrs["day_plan"] = payload["day_plan"]
        if payload.get("week") is not None:
            attrs["week"] = payload["week"]
        if payload.get("day_idx") is not None:
            attrs["day_idx"] = payload["day_idx"]
        return attrs

    return _fn


# ---------------------------------------------------------------------------
# Entity description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoymilesSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor and optional attributes."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # Capability the firmware must have declared for this entity to be created.
    # ``None`` means "always create" - used for the fields every model sends.
    requires: str | None = None
    # Capability the firmware must NOT have declared.  A few fields exist only on
    # the models that *lack* a topic - the per port energy counters live in
    # ``pvs[]`` and are only sent by a micro inverter, which is exactly the model
    # that has no ``system/state``.  Expressed as an absence so it keeps working
    # if a future storage model ever starts sending them.
    requires_absent: str | None = None
    # Skip the device watchdog for entities whose value comes from the
    # integration rather than from the device.  An offline device must not make
    # the keep-alive state unreadable, because the card uses it to decide whether
    # the lease is being held - exactly when that matters most.
    ignores_device_availability: bool = False


_POWER = {
    "device_class": SensorDeviceClass.POWER,
    "native_unit_of_measurement": UnitOfPower.WATT,
    "state_class": SensorStateClass.MEASUREMENT,
}
_ENERGY = {
    "device_class": SensorDeviceClass.ENERGY,
    "native_unit_of_measurement": UnitOfEnergy.WATT_HOUR,
    "state_class": SensorStateClass.TOTAL_INCREASING,
}
_VOLTAGE = {
    "device_class": SensorDeviceClass.VOLTAGE,
    "native_unit_of_measurement": UnitOfElectricPotential.VOLT,
    "state_class": SensorStateClass.MEASUREMENT,
}
_CURRENT = {
    "device_class": SensorDeviceClass.CURRENT,
    "native_unit_of_measurement": UnitOfElectricCurrent.AMPERE,
    "state_class": SensorStateClass.MEASUREMENT,
}
_FREQUENCY = {
    "device_class": SensorDeviceClass.FREQUENCY,
    "native_unit_of_measurement": UnitOfFrequency.HERTZ,
    "state_class": SensorStateClass.MEASUREMENT,
}
_TEMPERATURE = {
    "device_class": SensorDeviceClass.TEMPERATURE,
    "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
    "state_class": SensorStateClass.MEASUREMENT,
}
_SOC = {
    "device_class": SensorDeviceClass.BATTERY,
    "native_unit_of_measurement": PERCENTAGE,
    "state_class": SensorStateClass.MEASUREMENT,
}
_REACTIVE_POWER = {
    "device_class": SensorDeviceClass.REACTIVE_POWER,
    "native_unit_of_measurement": "var",
    "state_class": SensorStateClass.MEASUREMENT,
}


SENSOR_DESCRIPTIONS: tuple[HoymilesSensorDescription, ...] = (
    # ---------------- quick/state : device level (1 s) ----------------
    # A micro inverter (HiFlow) publishes ``quick/state`` too, but only with the
    # five ``sys_*`` aggregates - it has no battery and no per-port grid powers,
    # so these four would sit at "unknown" forever.  They are gated on the
    # ``system_state`` capability, which exactly the storage units declare.
    HoymilesSensorDescription(
        key="pv_power", name="PV Power", value_fn=q("pv_p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    HoymilesSensorDescription(
        key="grid_on_power", name="Grid On Power", value_fn=q("grid_on_p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    HoymilesSensorDescription(
        key="grid_off_power", name="Grid Off Power", value_fn=q("grid_off_p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    HoymilesSensorDescription(
        key="battery_status", name="Battery Status", value_fn=q("bat_sts"),
        requires=CAP_SYSTEM_STATE
    ),
    # ---------------- quick/state : system level (master/single) ----------------
    HoymilesSensorDescription(
        key="system_pv_power", name="System PV Power", value_fn=q("sys_pv_p"), **_POWER
    ),
    HoymilesSensorDescription(
        key="system_plug_power", name="System Plug Power", value_fn=q("sys_plug_p"), **_POWER
    ),
    HoymilesSensorDescription(
        key="system_battery_power", name="System Battery Power", value_fn=q("sys_bat_p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    HoymilesSensorDescription(
        key="system_grid_power", name="System Grid Power", value_fn=q("sys_grid_p"), **_POWER
    ),
    HoymilesSensorDescription(
        key="system_load_power", name="System Load Power", value_fn=q("sys_load_p"), **_POWER
    ),
    HoymilesSensorDescription(
        key="system_smart_plug_power", name="System Smart Plug Power", value_fn=q("sys_sp_p"), **_POWER
    ),
    HoymilesSensorDescription(
        key="system_soc", name="System SOC", value_fn=q("sys_soc"),
        requires=CAP_SYSTEM_STATE, **_SOC
    ),
    HoymilesSensorDescription(
        key="system_pv2_power", name="System PV2 Power", value_fn=q("sys_pv2_p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    HoymilesSensorDescription(
        key="system_eps_power", name="System EPS Power", value_fn=q("sys_eps_p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    # ---------------- device/state : battery & signal (5 min) ----------------
    HoymilesSensorDescription(
        key="battery_voltage", name="Battery Voltage", value_fn=d("bat_v"),
        requires=CAP_SYSTEM_STATE, **_VOLTAGE
    ),
    HoymilesSensorDescription(
        key="battery_current", name="Battery Current", value_fn=d("bat_i"),
        requires=CAP_SYSTEM_STATE, **_CURRENT
    ),
    HoymilesSensorDescription(
        key="battery_temperature", name="Battery Temperature", value_fn=d("bat_temp"),
        requires=CAP_SYSTEM_STATE, **_TEMPERATURE
    ),
    HoymilesSensorDescription(
        key="rssi",
        name="RSSI",
        value_fn=d("rssi"),
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---------------- device/state : grid on (index 0) ----------------
    HoymilesSensorDescription(
        key="grid_on_voltage", name="Grid On Voltage", value_fn=grid(0, "v"), **_VOLTAGE
    ),
    HoymilesSensorDescription(
        key="grid_on_current", name="Grid On Current", value_fn=grid(0, "i"), **_CURRENT
    ),
    HoymilesSensorDescription(
        key="grid_on_frequency", name="Grid On Frequency", value_fn=grid(0, "f"), **_FREQUENCY
    ),
    HoymilesSensorDescription(
        key="grid_on_power_5m", name="Grid On Power (5 min)", value_fn=grid(0, "p"), **_POWER
    ),
    HoymilesSensorDescription(
        key="grid_on_reactive_power", name="Grid On Reactive Power", value_fn=grid(0, "q"), **_REACTIVE_POWER
    ),
    # The grid array of a micro inverter has a single ``grid_on`` entry and no
    # ``ein``/``eout``/``etin``/``etout``, so everything below needs the storage
    # capability as well.
    HoymilesSensorDescription(
        key="grid_on_energy_in_today", name="Grid On Energy In Today", value_fn=grid(0, "ein"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="grid_on_energy_out_today", name="Grid On Energy Out Today", value_fn=grid(0, "eout"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="grid_on_energy_in_total", name="Grid On Energy In Total", value_fn=grid(0, "etin"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="grid_on_energy_out_total", name="Grid On Energy Out Total", value_fn=grid(0, "etout"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    # ---------------- device/state : grid off (index 1) ----------------
    HoymilesSensorDescription(
        key="grid_off_voltage", name="Grid Off Voltage", value_fn=grid(1, "v"),
        requires=CAP_SYSTEM_STATE, **_VOLTAGE
    ),
    HoymilesSensorDescription(
        key="grid_off_current", name="Grid Off Current", value_fn=grid(1, "i"),
        requires=CAP_SYSTEM_STATE, **_CURRENT
    ),
    HoymilesSensorDescription(
        key="grid_off_frequency", name="Grid Off Frequency", value_fn=grid(1, "f"),
        requires=CAP_SYSTEM_STATE, **_FREQUENCY
    ),
    HoymilesSensorDescription(
        key="grid_off_power_5m", name="Grid Off Power (5 min)", value_fn=grid(1, "p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    HoymilesSensorDescription(
        key="grid_off_reactive_power", name="Grid Off Reactive Power", value_fn=grid(1, "q"),
        requires=CAP_SYSTEM_STATE, **_REACTIVE_POWER
    ),
    HoymilesSensorDescription(
        key="grid_off_energy_in_today", name="Grid Off Energy In Today", value_fn=grid(1, "ein"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="grid_off_energy_out_today", name="Grid Off Energy Out Today", value_fn=grid(1, "eout"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="grid_off_energy_in_total", name="Grid Off Energy In Total", value_fn=grid(1, "etin"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="grid_off_energy_out_total", name="Grid Off Energy Out Total", value_fn=grid(1, "etout"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    # ---------------- device/state : inverter (index 2, no frequency) ----------------
    HoymilesSensorDescription(
        key="inv_voltage", name="Inverter Voltage", value_fn=grid(2, "v"),
        requires=CAP_SYSTEM_STATE, **_VOLTAGE
    ),
    HoymilesSensorDescription(
        key="inv_current", name="Inverter Current", value_fn=grid(2, "i"),
        requires=CAP_SYSTEM_STATE, **_CURRENT
    ),
    HoymilesSensorDescription(
        key="inv_power", name="Inverter Power", value_fn=grid(2, "p"),
        requires=CAP_SYSTEM_STATE, **_POWER
    ),
    HoymilesSensorDescription(
        key="inv_reactive_power", name="Inverter Reactive Power", value_fn=grid(2, "q"),
        requires=CAP_SYSTEM_STATE, **_REACTIVE_POWER
    ),
    HoymilesSensorDescription(
        key="inv_energy_in_today", name="Inverter Energy In Today", value_fn=grid(2, "ein"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="inv_energy_out_today", name="Inverter Energy Out Today", value_fn=grid(2, "eout"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="inv_energy_in_total", name="Inverter Energy In Total", value_fn=grid(2, "etin"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="inv_energy_out_total", name="Inverter Energy Out Total", value_fn=grid(2, "etout"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    # ---------------- device/state : PV ports ----------------
    # All four ports are created on every model, exactly like ``pv1`` / ``pv2``
    # always were.  The ``pvs[]`` array is what actually carries the readings and
    # its length varies per SKU - a 4161 2-in-1 reports two entries, a 4162
    # 4-in-1 reports four - so gating a port on a model string would hide a
    # genuine input.  A port the unit does not have simply stays ``unknown``,
    # which is the same "this input does not exist" signal the card already uses
    # to decide how many connectors to draw.
    HoymilesSensorDescription(
        key="pv1_power", name="PV1 Power", value_fn=pv(0), **_POWER
    ),
    HoymilesSensorDescription(
        key="pv2_power", name="PV2 Power", value_fn=pv(1), **_POWER
    ),
    HoymilesSensorDescription(
        key="pv3_power", name="PV3 Power", value_fn=pv(2), **_POWER
    ),
    HoymilesSensorDescription(
        key="pv4_power", name="PV4 Power", value_fn=pv(3), **_POWER
    ),
    # ---------------- device/state : per port PV energy (micro inverter) -------
    # Only the micro inverter firmware puts ``ed`` / ``et`` inside ``pvs[]``; a
    # storage unit reports the same information in ``system/state`` and leaves
    # both fields out.  Gated on the absence of that topic so the two sets of
    # energy sensors never overlap.  The *total* today figure is not repeated
    # here - ``system_pv_energy_today`` already falls back to the ``pvs[]`` sum.
    HoymilesSensorDescription(
        key="pv_energy_total", name="PV Energy Total",
        value_fn=pv_energy_total("et"),
        requires_absent=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="pv1_energy_today", name="PV1 Energy Today",
        value_fn=pv_energy(0, "ed"),
        requires_absent=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="pv2_energy_today", name="PV2 Energy Today",
        value_fn=pv_energy(1, "ed"),
        requires_absent=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="pv3_energy_today", name="PV3 Energy Today",
        value_fn=pv_energy(2, "ed"),
        requires_absent=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="pv4_energy_today", name="PV4 Energy Today",
        value_fn=pv_energy(3, "ed"),
        requires_absent=CAP_SYSTEM_STATE, **_ENERGY
    ),
    # ---------------- device/state : packs ----------------
    HoymilesSensorDescription(
        key="pack_count", name="Pack Count", value_fn=d("pack_num"),
        requires=CAP_SYSTEM_STATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HoymilesSensorDescription(
        key="pack1_soc", name="Pack 1 SOC", value_fn=pack(0, "soc"),
        requires=CAP_SYSTEM_STATE, **_SOC
    ),
    HoymilesSensorDescription(
        key="pack1_temperature", name="Pack 1 Temperature", value_fn=pack(0, "temp"),
        requires=CAP_SYSTEM_STATE, **_TEMPERATURE
    ),
    HoymilesSensorDescription(
        key="pack2_soc", name="Pack 2 SOC", value_fn=pack(1, "soc"),
        requires=CAP_SYSTEM_STATE, **_SOC
    ),
    HoymilesSensorDescription(
        key="pack2_temperature", name="Pack 2 Temperature", value_fn=pack(1, "temp"),
        requires=CAP_SYSTEM_STATE, **_TEMPERATURE
    ),
    HoymilesSensorDescription(
        key="pack3_soc", name="Pack 3 SOC", value_fn=pack(2, "soc"),
        requires=CAP_SYSTEM_STATE, **_SOC
    ),
    HoymilesSensorDescription(
        key="pack3_temperature", name="Pack 3 Temperature", value_fn=pack(2, "temp"),
        requires=CAP_SYSTEM_STATE, **_TEMPERATURE
    ),
    HoymilesSensorDescription(
        key="pack4_soc", name="Pack 4 SOC", value_fn=pack(3, "soc"),
        requires=CAP_SYSTEM_STATE, **_SOC
    ),
    HoymilesSensorDescription(
        key="pack4_temperature", name="Pack 4 Temperature", value_fn=pack(3, "temp"),
        requires=CAP_SYSTEM_STATE, **_TEMPERATURE
    ),
    # ---------------- system/state : daily energy (master/single) ----------------
    # These read ``system/state`` only, so a model without that topic would show
    # ``unknown`` forever.  Gate them like the rest of the storage fields, except
    # for the PV total below, which a micro inverter can also answer from
    # ``pvs[].ed``.
    HoymilesSensorDescription(
        key="system_pv_energy_today", name="System PV Energy Today",
        value_fn=s_or_pv("pv_e", "ed"), **_ENERGY
    ),
    HoymilesSensorDescription(
        key="system_pv2_energy_today", name="System PV2 Energy Today", value_fn=s("pv2_e"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="battery_charge_energy_today", name="Battery Charge Energy Today", value_fn=s("chg_e"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="battery_discharge_energy_today", name="Battery Discharge Energy Today", value_fn=s("dchg_e"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="plug_output_energy_today", name="Plug Output Energy Today", value_fn=s("plug_out_e"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="plug_input_energy_today", name="Plug Input Energy Today", value_fn=s("plug_in_e"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="eps_output_energy_today", name="EPS Output Energy Today", value_fn=s("eps_out_e"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    HoymilesSensorDescription(
        key="eps_input_energy_today", name="EPS Input Energy Today", value_fn=s("eps_in_e"),
        requires=CAP_SYSTEM_STATE, **_ENERGY
    ),
    # A storage unit reports the running mode in ``system/state``; a micro
    # inverter has no such topic and puts it in ``device/state`` instead, so the
    # extractor has to look at both.  Not gated: every model reports a mode.
    HoymilesSensorDescription(
        key="ems_mode_running", name="EMS Mode (Device)", value_fn=_ems_mode_value
    ),
    # ---------------- TOU ----------------
    HoymilesSensorDescription(
        key="tou_plan_status",
        name="TOU Plan Status",
        value_fn=_tou_status_value,
        attrs_fn=_tou_attrs(SRC_TOU_STATUS),
        requires=CAP_TOU,
    ),
    HoymilesSensorDescription(
        key="tou_day_ack",
        name="TOU Day Plan Ack",
        value_fn=_ack(SRC_TOU_DAY_ACK, TOU_DAY_ACK_STATUS),
        attrs_fn=_tou_attrs(SRC_TOU_DAY_ACK),
        requires=CAP_TOU,
    ),
    HoymilesSensorDescription(
        key="tou_week_ack",
        name="TOU Week Plan Ack",
        value_fn=_ack(SRC_TOU_WEEK_ACK, TOU_WEEK_ACK_STATUS),
        attrs_fn=_tou_attrs(SRC_TOU_WEEK_ACK),
        requires=CAP_TOU,
    ),
    # Integration-owned, not a device topic: whether the power-control lease is
    # being held, and how often. The control card reads it back so a dashboard
    # reload shows the truth instead of guessing from a local timer.
    HoymilesSensorDescription(
        key="power_ctrl_keepalive",
        name="Power Control Keep-alive",
        icon="mdi:timer-sync-outline",
        value_fn=_keepalive_value,
        attrs_fn=_keepalive_attrs,
        ignores_device_availability=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors from a config entry."""
    coordinator: HoymilesCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    dev_id: str = hass.data[DOMAIN][entry.entry_id]["dev_id"]

    # Which topics the firmware implements decides which sensors make sense; the
    # retained inventory usually arrives within milliseconds.
    await coordinator.async_wait_for_capabilities()

    async_add_entities(
        HoymilesSensor(coordinator, dev_id, description)
        for description in SENSOR_DESCRIPTIONS
        if (description.requires is None
            or coordinator.has_capability(description.requires))
        and (description.requires_absent is None
             or not coordinator.has_capability(description.requires_absent))
    )


class HoymilesSensor(CoordinatorEntity[HoymilesCoordinator], SensorEntity):
    """A push-updated sensor fed by the MQTT coordinator."""

    _attr_has_entity_name = True
    entity_description: HoymilesSensorDescription

    def __init__(
        self,
        coordinator: HoymilesCoordinator,
        dev_id: str,
        description: HoymilesSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{dev_id}_{description.key}"
        self._attr_name = description.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dev_id)},
            name=dev_id,
            manufacturer=MANUFACTURER,
        )

    @property
    def available(self) -> bool:
        """Return True while the device is still pushing data."""
        if self.entity_description.ignores_device_availability:
            return True
        return self.coordinator.available

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        value_fn = self.entity_description.value_fn
        if value_fn is None:
            return None
        return value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the raw payload fields for ack/status sensors."""
        attrs_fn = self.entity_description.attrs_fn
        if attrs_fn is None:
            return None
        attrs = attrs_fn(self.coordinator.data or {})
        return attrs or None
