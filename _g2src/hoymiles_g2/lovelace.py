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

The sidebar entry and the dashboard header read the bare serial, e.g.
``RMI-4161A0209FF6``.  Earlier releases prefixed the model (``HiFlow_<serial>``);
those titles are migrated to the bare serial exactly once, and from then on the
title belongs to the user - renaming the dashboard under
*Settings -> Dashboards* is permanent and is never overwritten on restart.

The model string is still resolved (from whichever registry entry carries one -
the firmware publishes its own MQTT discovery under the bare serial, and that
entry is the one with ``model`` filled in) but only to label the heading card at
the top of each view.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, MODEL_BY_PREFIX

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PREFIX = "g2-"
DASHBOARD_ICON = "mdi:solar-power-variant"

# url_paths whose stored title has already been inspected for a one-time
# migration.  Process-local on purpose: after a restart the check costs one
# storage read per device and is a no-op again once the title is the serial.
_TITLE_CHECKED: set[str] = set()

# url_paths whose view layout has already been inspected.  Same reasoning: one
# read per device per process, and nothing to do once upgraded.
_LAYOUT_CHECKED: set[str] = set()

# The view titles an earlier release wrote.  Used together with the absence of
# ``icon`` / ``max_columns`` as the fingerprint of an untouched old dashboard, so
# a layout upgrade can never overwrite a dashboard the user has edited.
_LEGACY_VIEW_TITLES: tuple[str, ...] = (
    "系统 / System",
    "设备 / Device",
    "控制 / Control",
)

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


def _dashboard_title(dev_id: str) -> str:
    """The default sidebar / header title: the bare serial.

    Only the serial, never ``<model>_<serial>``: the model string is not stable
    (it arrives later from the firmware's discovery, so the title used to change
    under the user's feet) and the user is free to rename the dashboard anyway -
    see :func:`_is_generated_title`.
    """
    return dev_id


def _is_generated_title(current: str, dev_id: str) -> bool:
    """True when ``current`` is a title a previous version wrote itself.

    Earlier releases titled these dashboards ``HiFlow_RMI-4161A0209FF6`` /
    ``HiFlow Pro_RMI-4161A0209FF6``.  Those are ours, so they may be migrated to
    the bare serial exactly once.  Anything else is a name the user chose and is
    never touched again.
    """
    if not current or current == dev_id:
        return False
    return current.endswith(f"_{dev_id}") or current.endswith(f"-{dev_id}")


async def _async_read_storage(hass: HomeAssistant, store: Any) -> Any:
    """Read a ``LovelaceStorage`` config across Home Assistant versions.

    The signature of ``async_load`` changed: some releases declare
    ``async_load(self)``, newer ones ``async_load(self, force: bool)``.  Calling
    it with no argument therefore raises ``TypeError`` on those releases - which
    the caller's broad ``except`` swallowed, silently disabling every layout
    upgrade.  ``force=True`` is passed where accepted so a dashboard written
    earlier in the same process is really re-read from disk instead of served
    from the in-memory cache.
    """
    loader = store.async_load
    try:
        params = inspect.signature(loader).parameters
    except (TypeError, ValueError):
        params = {}

    attempts: list[tuple[Any, ...]] = []
    if "force" in params or len(params) > 1:
        attempts.append((True,))
    attempts.append(())

    for args in attempts:
        try:
            return await loader(*args)
        except TypeError:
            continue
        except Exception:  # noqa: BLE001 - fall through to the file probe
            break

    return await _async_read_storage_file(hass, store)


async def _async_read_storage_file(hass: HomeAssistant, store: Any) -> Any:
    """Last-resort read of the dashboard JSON straight off disk.

    ``LovelaceStorage`` keeps its ``Store`` on a private attribute whose name has
    been stable for years, but the end of the world is not worth risking on it:
    every lookup is guarded and ``None`` simply means "cannot tell", which makes
    the caller leave the dashboard alone.
    """
    inner = getattr(store, "_store", None)
    key = getattr(inner, "key", None)
    if not isinstance(key, str) or not key.startswith("lovelace"):
        return None

    path = hass.config.path(".storage", key)
    try:
        raw = await hass.async_add_executor_job(_read_json_file, path)
    except Exception:  # noqa: BLE001
        return None

    if isinstance(raw, dict):
        return raw.get("data", {}).get("config", raw)
    return None


def _read_json_file(path: str) -> Any:
    """Read one JSON file, raising on any problem."""
    import json  # noqa: PLC0415

    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


async def async_ensure_dashboard(
    hass: HomeAssistant, dev_id: str, pv_count: int | None = None
) -> None:
    """Create the device's storage dashboard if it does not exist yet.

    Idempotent: a second call for the same device (or after a reload) is a
    no-op.  Every failure path logs a warning and returns, because a dashboard
    must never take down the integration.

    ``pv_count`` and the model name only affect dashboards created from scratch;
    an existing dashboard is left alone so user edits - including a rename -
    survive upgrades.
    """
    url_path = _url_path(dev_id)
    title = _dashboard_title(dev_id)
    model = _resolve_model(hass, dev_id)

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
    # The dashboard - and any name the user gave it - is left untouched; only a
    # title an older release generated is migrated, once.
    if url_path in dashboards:
        _LOGGER.debug("Dashboard %s already exists, leaving it alone", url_path)
        await _async_migrate_title(hass, dev_id, url_path, title)
        await _async_upgrade_layout(
            hass, dashboards[url_path], dev_id, url_path, pv_count, model
        )
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
        # Already created by an earlier version.  The views and the name are the
        # user's now: only a title this integration generated itself is migrated
        # to the bare serial, and only once - a rename must never be undone.
        _LOGGER.debug("Dashboard %s already in storage", url_path)
        current = existing.get(CONF_TITLE) or ""
        if _is_generated_title(current, dev_id):
            await _async_rename(collection, existing, url_path, title)
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
        await store.async_save({"views": _build_views(dev_id, pv_count, model)})
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


async def _async_migrate_title(
    hass: HomeAssistant, dev_id: str, url_path: str, title: str
) -> None:
    """Migrate an older generated title to the bare serial, at most once.

    The live dashboards dict is populated from storage before this integration's
    platforms are set up, so the fast path - not the storage branch - is where an
    existing dashboard is usually seen.  The title therefore has to be checked
    here, which means reading the dashboards collection; a per-process memo keeps
    that to a single read per device instead of one per reload.  After the first
    run the stored title equals ``dev_id`` and nothing further happens.
    """
    if url_path in _TITLE_CHECKED:
        return
    _TITLE_CHECKED.add(url_path)

    try:
        from homeassistant.components.lovelace import dashboard  # noqa: PLC0415
        from homeassistant.components.lovelace.const import (  # noqa: PLC0415
            CONF_TITLE,
            CONF_URL_PATH,
        )

        collection = dashboard.DashboardsCollection(hass)
        await collection.async_load()
        for item in collection.async_items():
            if item.get(CONF_URL_PATH) != url_path:
                continue
            if _is_generated_title(item.get(CONF_TITLE) or "", dev_id):
                await _async_rename(hass, collection, item, url_path, title)
            return
    except Exception:  # noqa: BLE001 - a title is never worth breaking setup for
        _LOGGER.debug("Could not inspect dashboard title for %s", url_path, exc_info=True)


async def _async_rename(
    hass: HomeAssistant,
    collection: Any,
    item: dict[str, Any],
    url_path: str,
    title: str,
) -> None:
    """Write ``title`` into the dashboards collection and the sidebar.

    Only ever reached for a title :func:`_is_generated_title` recognises as ours,
    so a user-chosen name is never overwritten.
    """
    try:
        from homeassistant.components.lovelace.const import CONF_TITLE  # noqa: PLC0415

        await collection.async_update_item(item["id"], {CONF_TITLE: title})
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not retitle dashboard %s", url_path, exc_info=True)
        return

    _LOGGER.info("Migrated dashboard %s title to %s", url_path, title)
    _sync_sidebar_title(hass, url_path, title)


async def _async_upgrade_layout(
    hass: HomeAssistant,
    store: Any,
    dev_id: str,
    url_path: str,
    pv_count: int | None,
    model: str,
) -> None:
    """Rewrite a dashboard that still carries the old generated layout.

    Upgrades are why :func:`_is_legacy_layout` exists: only a dashboard that is
    byte-for-byte what an earlier release produced is replaced, so a dashboard
    the user has touched is never overwritten.  Verified once per device per
    process, because ``LovelaceStorage`` caches its config in memory.
    """
    if url_path in _LAYOUT_CHECKED:
        return
    _LAYOUT_CHECKED.add(url_path)

    try:
        config = await _async_read_storage(hass, store) or {}
    except Exception:  # noqa: BLE001 - a layout is never worth breaking setup for
        _LOGGER.warning("Could not read dashboard %s", url_path, exc_info=True)
        return

    if not _is_legacy_layout(config):
        return

    try:
        await store.async_save({"views": _build_views(dev_id, pv_count, model)})
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not upgrade dashboard %s", url_path, exc_info=True)
        return

    _LOGGER.info("Upgraded dashboard %s to the current layout", url_path)


def _is_legacy_layout(config: Any) -> bool:
    """True when ``config`` is exactly the layout an earlier release wrote.

    The fingerprint is the combination of the old view titles with the absence of
    the view-level keys this release adds (``icon``, ``max_columns``,
    ``show_icon_and_title``).  A dashboard where the user renamed, reordered,
    removed or added a view - or edited any card - fails one of those checks and
    is left alone.
    """
    if not isinstance(config, dict):
        return False
    views = config.get("views")
    if not isinstance(views, list) or len(views) != len(_LEGACY_VIEW_TITLES):
        return False
    for view, legacy_title in zip(views, _LEGACY_VIEW_TITLES, strict=True):
        if not isinstance(view, dict):
            return False
        if view.get("title") != legacy_title:
            return False
        if "icon" in view or "max_columns" in view or "show_icon_and_title" in view:
            return False
    return True


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


def _build_views(
    dev_id: str, pv_count: int | None = None, model: str = ""
) -> list[dict[str, Any]]:
    """Return the three views for the device.

    ``pv_count`` is how many PV inputs the unit actually has, so the inverter
    views only reference per-port entities that exist.  ``None`` means "not
    known yet" and is treated as two, the common case for the inverter family
    this layout targets.  ``model`` only feeds the heading text.
    """
    if _is_inverter(dev_id):
        return _build_inverter_views(dev_id, pv_count, model)
    return _build_storage_views(dev_id, model)


# Icon shown on each view's tab; the same three every generated dashboard uses.
_VIEW_ICONS: dict[str, str] = {
    "system": "mdi:solar-power-variant",
    "device": "mdi:solar-panel-large",
    "control": "mdi:tune",
}


def _view(
    path: str,
    title: str,
    sections: list[dict[str, Any]],
    *,
    icon: str | None = None,
) -> dict[str, Any]:
    """Assemble a single sections view.

    ``max_columns: 4`` and ``show_icon_and_title`` are emitted for every view so
    a generated dashboard looks the same on a wide screen as a hand-made one:
    the title bar keeps the icon visible instead of collapsing the tab strip.
    """
    return {
        "type": "sections",
        "path": path,
        "title": title,
        "icon": icon or _VIEW_ICONS.get(path, DASHBOARD_ICON),
        "max_columns": 4,
        "show_icon_and_title": True,
        "sections": sections,
    }


def _grid(cards: list[dict[str, Any]], column_span: int = 4) -> dict[str, Any]:
    """A grid section holding the given cards."""
    return {"type": "grid", "column_span": column_span, "cards": cards}


def _subgrid(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """A nested two-column grid card, used to place cards side by side."""
    return {
        "type": "grid",
        "columns": 2,
        "square": False,
        "grid_options": {"columns": "full"},
        "cards": cards,
    }


def _full_width(card: dict[str, Any]) -> dict[str, Any]:
    """Mark a card as spanning every column of its grid."""
    out = dict(card)
    out["grid_options"] = {"columns": "full"}
    return out


def _heading(model: str, kind: str) -> dict[str, Any]:
    """The ``<model> · <family>`` heading card at the top of a view."""
    label = "微型逆变器" if kind == "inverter" else "储能系统"
    text = f"{model} · {label}" if model else label
    return {"type": "heading", "heading": text, "heading_style": "title"}


def _history(
    title: dict[str, str],
    series: list[dict[str, Any]],
    *,
    unit: str,
    height: int,
    sync_group: str | None = None,
    span: float | None = None,
) -> dict[str, Any]:
    """A ``hoymiles-g2-history-chart`` card spanning the full section width."""
    card: dict[str, Any] = {
        "type": "custom:hoymiles-g2-history-chart",
        "title": title,
        "range": "day",
        "series": series,
        "unit": unit,
        "height": height,
    }
    if sync_group is not None:
        card["sync_group"] = sync_group
    if span is not None:
        card["span"] = span
    return _full_width(card)


# --------------------------------------------------------------------------- #
# Micro inverter (RMI-) views
# --------------------------------------------------------------------------- #
def _build_inverter_views(
    dev_id: str, pv_count: int | None = None, model: str = ""
) -> list[dict[str, Any]]:
    """System / device / control views for a grid-tied micro inverter.

    Mirrors the hand-built reference dashboard: a heading card naming the
    product, one full-width power flow, and history charts that share a
    ``sync_group`` so every curve on a page moves with the same time window.

    Every per-port reference is generated from ``pv_count`` so a single-input
    unit does not get gauges and history series pointing at sensors that this
    integration never created for it.
    """
    ports = pv_count if pv_count and pv_count >= 1 else 2
    slug = _slug(dev_id)
    system_group = f"{slug}-system"
    device_group = f"{slug}-device"

    pv_series = {
        "entity": _entity(dev_id, "system_pv_power"),
        "name": _t("PV power", "光伏功率"),
        "color": "#22c55e",
    }
    grid_series = {
        "entity": _entity(dev_id, "system_grid_power"),
        "name": _t("Grid output [+]/input [-]", "电网 输出[+]/输入[-]"),
        "color": "#22d3ee",
    }
    load_series = {
        "entity": _entity(dev_id, "system_load_power"),
        "name": _t("Load", "负载"),
        "color": "#f5a623",
    }

    # One curve per port that exists; the colours match the port gauges.
    _PORT_COLORS = ("#22c55e", "#4a90d9", "#8b5cf6", "#06b6d4")
    port_series = [
        {
            "entity": _entity(dev_id, f"pv{port}_power"),
            "name": _t(f"PV{port}", f"PV{port}"),
            "color": _PORT_COLORS[(port - 1) % len(_PORT_COLORS)],
        }
        for port in range(1, ports + 1)
    ]

    power_flow = {
        "type": "custom:hoymiles-g2-power-flow",
        "dev_id": dev_id,
        "title": _t("My home", "我的家"),
        "max_width": 700,
        "show_title": False,
    }

    system = _view(
        "system",
        "System",
        [
            _grid(
                [
                    _heading(model, "inverter"),
                    _subgrid(
                        [
                            _full_width(power_flow),
                            _subgrid(
                                [
                                    _gauge(
                                        dev_id,
                                        "system_pv_energy_today",
                                        _t("PV today", "今日发电"),
                                        "Wh",
                                        max=2000,
                                        decimals=0,
                                        icon="☀️",
                                        show_arc=False,
                                    )
                                ]
                            ),
                        ]
                    ),
                ]
            ),
            _grid(
                [
                    _history(
                        _t("Power", "功率"),
                        [pv_series, grid_series, load_series],
                        unit="W",
                        height=330,
                        sync_group=system_group,
                    )
                ]
            ),
        ],
    )

    device = _view(
        "device",
        "Device",
        [
            _grid(
                [
                    _full_width(
                        {
                            **power_flow,
                            "variant": "inverter",
                            "pv_count": ports,
                        }
                    )
                ]
            ),
            _grid(
                [
                    _history(
                        _t("PV power by port", "各光伏端口功率"),
                        port_series,
                        unit="W",
                        height=280,
                        sync_group=device_group,
                        span=2000,
                    )
                ]
            ),
            _grid(
                [
                    _history(
                        _t("Total power", "功率曲线"),
                        [pv_series, grid_series, load_series],
                        unit="W",
                        height=300,
                        sync_group=device_group,
                        span=2500,
                    )
                ]
            ),
            _grid(
                [
                    _history(
                        _t("Grid voltage", "电网电压"),
                        [
                            {
                                "entity": _entity(dev_id, "grid_on_voltage"),
                                "name": _t("Grid voltage", "电网电压"),
                                "color": "#60a5fa",
                            }
                        ],
                        unit="V",
                        height=240,
                        sync_group=device_group,
                    ),
                    _history(
                        _t("Energy today", "今日发电量"),
                        [
                            {
                                "entity": _entity(dev_id, "system_pv_energy_today"),
                                "name": _t("PV today", "今日发电"),
                                "color": "#fbbf24",
                            }
                        ],
                        unit="Wh",
                        height=240,
                        sync_group=device_group,
                    ),
                ]
            ),
        ],
    )

    control = _view(
        "control",
        "Control",
        [
            _grid(
                [
                    _heading(model, "inverter"),
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-control",
                            "dev_id": dev_id,
                            "subtitle": False,
                            "entities": {
                                "output_power": f"number.{slug}",
                            },
                        }
                    ),
                ]
            )
        ],
    )

    return [system, device, control]


# --------------------------------------------------------------------------- #
# Storage (MSA-) views
# --------------------------------------------------------------------------- #
def _build_storage_views(dev_id: str, model: str = "") -> list[dict[str, Any]]:
    """System / device / control views for a micro storage unit.

    Same frame as the inverter layout - heading card, full-width power flow,
    icon and title on every view, shared ``sync_group`` on the history charts.
    """
    slug = _slug(dev_id)
    group = f"{slug}-system"
    system = _view(
        "system",
        "System",
        [
            _grid(
                [
                    _heading(model, "storage"),
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-power-flow",
                            "dev_id": dev_id,
                            "title": _t("My home", "我的家"),
                            "max_width": 700,
                            "show_title": False,
                        }
                    ),
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
                    _history(
                        _t("Power", "功率"),
                        [
                            {
                                "entity": _entity(dev_id, "system_pv_power"),
                                "name": _t("PV power", "光伏功率"),
                                "color": "#22c55e",
                            },
                            {
                                "entity": _entity(dev_id, "system_battery_power"),
                                "name": _t("Battery", "电池"),
                                "color": "#4a90d9",
                            },
                            {
                                "entity": _entity(dev_id, "system_grid_power"),
                                "name": _t("Grid output [+]/input [-]", "电网 输出[+]/输入[-]"),
                                "color": "#22d3ee",
                            },
                        ],
                        unit="W",
                        height=330,
                        sync_group=group,
                    )
                ]
            ),
            _grid(
                [
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-energy-sankey",
                            "dev_id": dev_id,
                            "title": _t("Energy flow", "能量流"),
                            "range": "today",
                        }
                    )
                ]
            ),
        ],
    )

    device = _view(
        "device",
        "Device",
        [
            _grid(
                [
                    _heading(model, "storage"),
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-battery",
                            "dev_id": dev_id,
                            "title": _t("Battery", "电池"),
                        }
                    ),
                ]
            ),
            _grid(
                [
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-pack-list",
                            "dev_id": dev_id,
                            "title": _t("Battery packs", "电池组"),
                            "columns": 2,
                        }
                    )
                ]
            ),
            _grid([_diagnostics(dev_id, inverter=False)]),
        ],
    )

    control = _view(
        "control",
        "Control",
        [
            _grid(
                [
                    _heading(model, "storage"),
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-control",
                            "dev_id": dev_id,
                            "subtitle": False,
                        }
                    ),
                ]
            ),
            _grid(
                [
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-tou-editor",
                            "dev_id": dev_id,
                            "title": _t("TOU plan", "峰谷计划"),
                        }
                    )
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
    decimals: int | None = None,
    icon: str | None = None,
    show_arc: bool | None = None,
) -> dict[str, Any]:
    """Build a ``hoymiles-g2-gauge`` card for one energy/power/SOC entity."""
    card: dict[str, Any] = {
        "type": "custom:hoymiles-g2-gauge",
        "entity": _entity(dev_id, key),
        "name": name,
        "unit": unit,
    }
    # Only non-default options are emitted: the card already defaults to
    # ``scale: 1`` / ``min: 0``, and carrying them in every card made the
    # generated YAML noisier than the hand-written dashboard it mirrors.
    if scale != 1:
        card["scale"] = scale
    if max is not None:
        card["max"] = max
    if min:
        card["min"] = min
    if decimals is not None:
        card["decimals"] = decimals
    if icon is not None:
        card["icon"] = icon
    if show_arc is not None:
        card["show_arc"] = show_arc
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
