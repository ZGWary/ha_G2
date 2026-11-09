"""Best-effort Lovelace dashboard creation for a Hoymiles MS-G2 device.

Home Assistant's ``lovelace`` component does not expose a public API for
creating a storage dashboard, so this module reaches into its internals
(``DashboardsCollection`` and ``LovelaceStorage``) the same way the built-in
map panel does.  Those internals are deprecated in core and slated for removal,
so *every* operation here is wrapped and must never raise - a failed dashboard
is logged and skipped, never allowed to break device setup.

The dashboard mirrors the official integration's G3-prefixed panels: three
views (system / device / control) built from the bundled cards, keyed to the
device's entities.  A micro inverter (``RMI-`` serial) gets the inverter layout;
a storage unit gets the full four-branch schematic plus battery and TOU cards.

The sidebar entry and the dashboard header both read ``<model>_<serial>``, e.g.
``HiFlow_RMI-4161A0209FF6``.  The model is not carried by this integration's own
device entry, so it is read from whichever registry entry has one - the firmware
publishes its own MQTT discovery under the bare serial, and that entry is the one
with ``model`` filled in.  A serial prefix fallback keeps the title useful on the
very first setup, before discovery has been processed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, MODEL_BY_PREFIX

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PREFIX = "g2-"
DASHBOARD_ICON = "mdi:solar-power-variant"

# Serial prefixes, used only when no registry entry carries a model string yet.
# ``RMI-`` is the grid-tied micro inverter family, ``MSA-`` the micro storage one.
_MODEL_BY_PREFIX: dict[str, str] = dict(MODEL_BY_PREFIX)

# Entity ids are ``sensor.<slug(dev_id)>_<key>``.  Only keys whose display name
# slugifies back to the key are safe to reference explicitly below - a few
# (``grid_on_power_5m`` -> "Grid On Power (5 min)", ``ems_mode_running`` ->
# "EMS Mode (Device)") do not round-trip, so they are deliberately absent here
# and are left to the cards' dev_id-based resolution instead.
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(dev_id: str) -> str:
    """Lower-case the serial and turn every non-alphanumeric run into ``_``."""
    return _SLUG_RE.sub("_", dev_id.lower()).strip("_")


def _url_path(dev_id: str) -> str:
    """Return the dashboard url slug, e.g. ``g2-rmi-4161a0209ff6``."""
    return f"{DASHBOARD_URL_PREFIX}{_slug(dev_id)}"


def _is_inverter(dev_id: str) -> bool:
    """True for a grid-tied micro inverter (``RMI-`` serial prefix)."""
    return dev_id.upper().startswith("RMI-")


def _entity(dev_id: str, key: str) -> str:
    """Build the conventional entity id ``sensor.<slug>_<key>``."""
    return f"sensor.{_slug(dev_id)}_{key}"


def _t(en: str, zh: str) -> dict[str, str]:
    """A language map the cards resolve against the viewing user's UI."""
    return {"en": en, "zh": zh}


def _identity_keys(dev_id: str) -> set[str]:
    """Every spelling a device registry entry may use for this serial.

    This integration registers ``(DOMAIN, "RMI-4161A0209FF6")`` while the
    firmware's own MQTT discovery registers ``4161A0209FF6`` - same hardware,
    two identifiers - so both spellings have to match.
    """
    lowered = dev_id.lower()
    keys = {lowered, _slug(lowered), _slug(lowered).replace("_", "")}
    if "-" in dev_id:
        keys.add(dev_id.rsplit("-", 1)[-1].lower())
    return keys


def _device_model(device: Any) -> str:
    """Model string of a device registry entry, or ``""``."""
    for attr in ("model", "model_id"):
        value = getattr(device, attr, None)
        if value:
            return str(value)
    return ""


def _resolve_model(hass: HomeAssistant, dev_id: str) -> str:
    """Return this device's product name, e.g. ``HiFlow`` or ``HiBattery 4020 X``.

    Read from the device registry because the model is not a config entry value:
    the firmware's own retained discovery carries it.  Falls back to the serial
    prefix so the very first setup already gets a sensible title.
    """
    try:
        from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

        registry = dr.async_get(hass)
    except Exception:  # noqa: BLE001 - a title is never worth breaking setup for
        registry = None

    if registry is not None:
        try:
            own = registry.async_get_device(identifiers={(DOMAIN, dev_id)})
        except Exception:  # noqa: BLE001
            own = None
        if own is not None:
            model = _device_model(own)
            if model:
                return model

        keys = _identity_keys(dev_id)
        for device in list(registry.devices.values()):
            for pair in device.identifiers:
                if not pair or pair[1] is None:
                    continue
                candidate = str(pair[1]).lower()
                if candidate in keys or candidate.replace("-", "") in keys:
                    model = _device_model(device)
                    if model:
                        return model

    upper = dev_id.upper()
    for prefix, name in _MODEL_BY_PREFIX.items():
        if upper.startswith(prefix):
            return name
    return ""


def _dashboard_title(dev_id: str, model: str) -> str:
    """The sidebar / header title: ``HiFlow_RMI-4161A0209FF6``."""
    return f"{model}_{dev_id}" if model else dev_id


async def async_ensure_dashboard(
    hass: HomeAssistant, dev_id: str, pv_count: int | None = None
) -> None:
    """Create the device's storage dashboard if it does not exist yet.

    Idempotent: a second call for the same device (or after a reload) is a
    no-op.  Every failure path logs a warning and returns, because a dashboard
    must never take down the integration.

    ``pv_count`` only affects dashboards created from scratch; an existing
    dashboard is left alone so user edits survive upgrades.
    """
    url_path = _url_path(dev_id)
    title = _dashboard_title(dev_id, _resolve_model(hass, dev_id))

    try:
        from homeassistant.components import frontend  # noqa: PLC0415
        from homeassistant.components.lovelace import dashboard  # noqa: PLC0415
        from homeassistant.components.lovelace.const import (  # noqa: PLC0415
            CONF_ALLOW_SINGLE_WORD,
            CONF_ICON,
            CONF_REQUIRE_ADMIN,
            CONF_SHOW_IN_SIDEBAR,
            CONF_TITLE,
            CONF_URL_PATH,
        )
    except ImportError:
        _LOGGER.debug("Lovelace internals unavailable, skipping dashboard for %s", dev_id)
        return

    lovelace_data = hass.data.get("lovelace")
    if lovelace_data is None:
        _LOGGER.debug("Lovelace not loaded, skipping dashboard for %s", dev_id)
        return

    dashboards = getattr(lovelace_data, "dashboards", None)
    if dashboards is None:
        _LOGGER.warning("No dashboards registry, skipping dashboard for %s", dev_id)
        return

    # Fast path: the dashboards dict is already populated and knows this slug.
    if url_path in dashboards:
        _LOGGER.debug("Dashboard %s already exists", url_path)
        _sync_sidebar_title(hass, url_path, title)
        return

    try:
        collection = dashboard.DashboardsCollection(hass)
        await collection.async_load()
        existing = None
        for candidate in collection.async_items():
            if candidate.get(CONF_URL_PATH) == url_path:
                existing = candidate
                break
    except Exception:  # noqa: BLE001 - never break setup because of a dashboard
        _LOGGER.warning("Could not inspect dashboards collection for %s", dev_id, exc_info=True)
        return

    if existing is not None:
        # Already created by an earlier version: the views are the user's now,
        # only the title is ours to keep in sync.
        _LOGGER.debug("Dashboard %s already in storage", url_path)
        if existing.get(CONF_TITLE) != title:
            await _async_rename(hass, collection, existing, url_path, title)
        else:
            _sync_sidebar_title(hass, url_path, title)
        return

    # Create the dashboard entry in ``.storage/lovelace_dashboards``.
    try:
        item = await collection.async_create_item(
            {
                CONF_ALLOW_SINGLE_WORD: True,
                CONF_ICON: DASHBOARD_ICON,
                CONF_TITLE: title,
                CONF_URL_PATH: url_path,
            }
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not create dashboard entry for %s", dev_id, exc_info=True)
        return

    # Persist the views into ``.storage/lovelace.<id>``.
    try:
        store = dashboard.LovelaceStorage(hass, item)
        await store.async_save({"views": _build_views(dev_id, pv_count)})
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not save dashboard views for %s", dev_id, exc_info=True)
        try:
            await collection.async_delete_item(item["id"])
        except Exception:  # noqa: BLE001
            pass
        return

    # Adopt the new store into the live registry, then register the sidebar
    # panel.  ``async_register_built_in_panel`` is a plain @callback, so it is
    # called synchronously (never awaited).
    dashboards[url_path] = store

    try:
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            sidebar_title=title,
            sidebar_icon=DASHBOARD_ICON,
            frontend_url_path=url_path,
            config={"mode": "storage"},
            require_admin=item.get(CONF_REQUIRE_ADMIN, False),
            show_in_sidebar=item.get(CONF_SHOW_IN_SIDEBAR, True),
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not register dashboard panel for %s", dev_id, exc_info=True)
        return

    _LOGGER.info("Created Lovelace dashboard %s (%s)", url_path, title)


async def _async_rename(
    hass: HomeAssistant,
    collection: Any,
    item: dict[str, Any],
    url_path: str,
    title: str,
) -> None:
    """Retitle an existing dashboard and re-register its sidebar entry.

    The title is recomputed on every setup because the model string only becomes
    known once the firmware's discovery has been processed: a device added before
    that point starts out with just the serial.
    """
    try:
        from homeassistant.components.lovelace.const import CONF_TITLE  # noqa: PLC0415

        await collection.async_update_item(item["id"], {CONF_TITLE: title})
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not retitle dashboard %s", url_path, exc_info=True)
        return

    _sync_sidebar_title(hass, url_path, title)


def _sync_sidebar_title(hass: HomeAssistant, url_path: str, title: str) -> None:
    """Make the generated sidebar entry carry ``title``.

    Re-registering the built-in ``lovelace`` panel is the only supported way to
    change a dashboard's sidebar label - it replaces the entry created when the
    dashboard itself was added, and leaving the old label in place would be worse
    than the extra call.  ``async_register_built_in_panel`` is a @callback, so it
    is called synchronously.
    """
    try:
        from homeassistant.components import frontend  # noqa: PLC0415

        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            sidebar_title=title,
            sidebar_icon=DASHBOARD_ICON,
            frontend_url_path=url_path,
            config={"mode": "storage"},
            require_admin=False,
            show_in_sidebar=True,
            update=True,
        )
    except TypeError:
        # Older core without the ``update`` keyword: nothing to sync.
        _LOGGER.debug("Sidebar panel for %s left unchanged", url_path)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not sync sidebar title for %s", url_path, exc_info=True)


def _build_views(dev_id: str, pv_count: int | None = None) -> list[dict[str, Any]]:
    """Return the three views for the device.

    ``pv_count`` is how many PV inputs the unit actually has, so the inverter
    views only reference per-port entities that exist.  ``None`` means "not
    known yet" and is treated as two, the common case for the inverter family
    this layout targets.
    """
    if _is_inverter(dev_id):
        return _build_inverter_views(dev_id, pv_count)
    return _build_storage_views(dev_id)


def _view(path: str, title: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble a single sections view."""
    return {
        "type": "sections",
        "path": path,
        "title": title,
        "sections": sections,
    }


def _grid(cards: list[dict[str, Any]], column_span: int = 2) -> dict[str, Any]:
    """A full-width (two-column) grid section holding the given cards."""
    return {"type": "grid", "column_span": column_span, "cards": cards}


# --------------------------------------------------------------------------- #
# Micro inverter (RMI-) views
# --------------------------------------------------------------------------- #
def _build_inverter_views(
    dev_id: str, pv_count: int | None = None
) -> list[dict[str, Any]]:
    """System / device / control views for a grid-tied micro inverter.

    Every per-port reference is generated from ``pv_count`` so a single-input
    unit does not get gauges and history series pointing at sensors that this
    integration never created for it.
    """
    ports = pv_count if pv_count and pv_count >= 1 else 2
    pv_power = _entity(dev_id, "system_pv_power")
    grid_power = _entity(dev_id, "system_grid_power")
    load_power = _entity(dev_id, "system_load_power")
    smart_plug = _entity(dev_id, "system_smart_plug_power")

    # One gauge per port that exists, appended after the two totals.
    _PORT_COLORS = ("#22c55e", "#f59e0b", "#8b5cf6", "#06b6d4")
    port_gauges = [
        _gauge(
            dev_id,
            f"pv{port}_energy_today",
            _t(f"PV{port} today", f"PV{port} 今日"),
            "kWh",
            scale=0.001,
        )
        for port in range(1, ports + 1)
    ]
    port_series = [
        {
            "entity": _entity(dev_id, f"pv{port}_power"),
            "name": _t(f"PV{port}", f"PV{port}"),
            "color": _PORT_COLORS[(port - 1) % len(_PORT_COLORS)],
        }
        for port in range(1, ports + 1)
    ]

    system = _view(
        "system",
        "系统 / System",
        [
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-power-flow",
                        "dev_id": dev_id,
                        "title": _t("My home", "我的家"),
                    }
                ]
            ),
            _grid(
                [
                    _gauge(
                        dev_id,
                        "system_pv_energy_today",
                        _t("PV today", "今日发电"),
                        "kWh",
                        scale=0.001,
                        icon="☀️",
                    ),
                    _gauge(
                        dev_id,
                        "pv_energy_total",
                        _t("PV total", "累计发电"),
                        "kWh",
                        scale=0.001,
                        icon="☀️",
                    ),
                    *port_gauges,
                ]
            ),
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-history-chart",
                        "dev_id": dev_id,
                        "title": _t("History", "历史数据"),
                        "range": "day",
                        "height": 330,
                        "unit": "W",
                        "series": [
                            *port_series,
                            {"entity": grid_power, "name": _t("Grid", "电网"), "color": "#4a90d9"},
                        ],
                    }
                ]
            ),
        ],
    )

    device = _view(
        "device",
        "设备 / Device",
        [
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-power-flow",
                        "dev_id": dev_id,
                        "variant": "inverter",
                        "title": _t("Device", "设备"),
                        "show_title": False,
                    }
                ]
            ),
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-gauge",
                        "entity": pv_power,
                        "name": _t("PV power", "发电功率"),
                        "unit": "W",
                        "decimals": 0,
                        "icon": "☀️",
                    },
                    {
                        "type": "custom:hoymiles-g2-gauge",
                        "entity": grid_power,
                        "name": _t("Grid power", "电网功率"),
                        "unit": "W",
                        "decimals": 0,
                        "icon": "⚡",
                    },
                    {
                        "type": "custom:hoymiles-g2-gauge",
                        "entity": load_power,
                        "name": _t("Load power", "负载功率"),
                        "unit": "W",
                        "decimals": 0,
                        "icon": "🏠",
                    },
                    {
                        "type": "custom:hoymiles-g2-gauge",
                        "entity": smart_plug,
                        "name": _t("Smart plug", "智能插座"),
                        "unit": "W",
                        "decimals": 0,
                        "icon": "🔌",
                    },
                ]
            ),
            _grid([_diagnostics(dev_id, inverter=True)]),
        ],
    )

    control = _view(
        "control",
        "控制 / Control",
        [
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-control",
                        "dev_id": dev_id,
                        "title": _t("Control", "设备控制"),
                    }
                ]
            )
        ],
    )

    return [system, device, control]


# --------------------------------------------------------------------------- #
# Storage (MSA-) views
# --------------------------------------------------------------------------- #
def _build_storage_views(dev_id: str) -> list[dict[str, Any]]:
    """System / device / control views for a micro storage unit."""
    system = _view(
        "system",
        "系统 / System",
        [
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-power-flow",
                        "dev_id": dev_id,
                        "title": _t("My home", "我的家"),
                    }
                ]
            ),
            _grid(
                [
                    _gauge(
                        dev_id,
                        "system_pv_energy_today",
                        _t("PV today", "今日发电"),
                        "kWh",
                        scale=0.001,
                        icon="☀️",
                    ),
                    _gauge(
                        dev_id,
                        "battery_charge_energy_today",
                        _t("Charge today", "今日充电"),
                        "kWh",
                        scale=0.001,
                        icon="⚡",
                    ),
                    _gauge(
                        dev_id,
                        "battery_discharge_energy_today",
                        _t("Discharge today", "今日放电"),
                        "kWh",
                        scale=0.001,
                        icon="🔋",
                    ),
                    _gauge(
                        dev_id,
                        "system_soc",
                        _t("Battery SOC", "电池电量"),
                        "%",
                        max=100,
                        min=0,
                        icon="🔋",
                    ),
                ]
            ),
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-history-chart",
                        "dev_id": dev_id,
                        "title": _t("History", "历史数据"),
                        "range": "day",
                        "height": 330,
                        "unit": "W",
                        "series": [
                            {"entity": _entity(dev_id, "system_pv_power"), "name": _t("PV", "发电"), "color": "#22c55e"},
                            {"entity": _entity(dev_id, "system_battery_power"), "name": _t("Battery", "电池"), "color": "#4a90d9"},
                            {"entity": _entity(dev_id, "system_grid_power"), "name": _t("Grid", "电网"), "color": "#f59e0b"},
                        ],
                    }
                ]
            ),
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-energy-sankey",
                        "dev_id": dev_id,
                        "title": _t("Energy flow", "能量流"),
                        "range": "today",
                    }
                ]
            ),
        ],
    )

    device = _view(
        "device",
        "设备 / Device",
        [
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-battery",
                        "dev_id": dev_id,
                        "title": _t("Battery", "电池"),
                    }
                ]
            ),
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-pack-list",
                        "dev_id": dev_id,
                        "title": _t("Battery packs", "电池组"),
                        "columns": 2,
                    }
                ]
            ),
            _grid([_diagnostics(dev_id, inverter=False)]),
        ],
    )

    control = _view(
        "control",
        "控制 / Control",
        [
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-control",
                        "dev_id": dev_id,
                        "title": _t("Control", "设备控制"),
                    }
                ]
            ),
            _grid(
                [
                    {
                        "type": "custom:hoymiles-g2-tou-editor",
                        "dev_id": dev_id,
                        "title": _t("TOU plan", "峰谷计划"),
                    }
                ]
            ),
        ],
    )

    return [system, device, control]


def _gauge(
    dev_id: str,
    key: str,
    name: dict[str, str],
    unit: str,
    *,
    scale: float = 1,
    max: float | None = None,
    min: float = 0,
    icon: str | None = None,
) -> dict[str, Any]:
    """Build a ``hoymiles-g2-gauge`` card for one energy/power/SOC entity."""
    card: dict[str, Any] = {
        "type": "custom:hoymiles-g2-gauge",
        "entity": _entity(dev_id, key),
        "name": name,
        "unit": unit,
        "scale": scale,
    }
    if max is not None:
        card["max"] = max
    if min is not None:
        card["min"] = min
    if icon is not None:
        card["icon"] = icon
    return card


def _diagnostics(dev_id: str, *, inverter: bool) -> dict[str, Any]:
    """A markdown card showing device identity and a few live readings."""
    slug = _slug(dev_id)
    rows = [
        f"## {dev_id}",
        "",
        "| 项目 | 值 |",
        "| --- | --- |",
        f"| RSSI | {{{{ states('sensor.{slug}_rssi') }}}} dBm |",
    ]
    if inverter:
        rows += [
            f"| 电网电压 | {{{{ states('sensor.{slug}_grid_on_voltage') }}}} V |",
            f"| 电网频率 | {{{{ states('sensor.{slug}_grid_on_frequency') }}}} Hz |",
        ]
    else:
        rows += [
            f"| 电池电压 | {{{{ states('sensor.{slug}_battery_voltage') }}}} V |",
            f"| 电池温度 | {{{{ states('sensor.{slug}_battery_temperature') }}}} ℃ |",
        ]
    return {"type": "markdown", "content": "\n".join(rows)}
