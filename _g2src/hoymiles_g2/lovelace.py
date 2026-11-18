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
entry is the one with ``model`` filled in) but no longer reaches the dashboard:
revision 11 dropped the heading card that used to print it, because that text was
built in Python and could not follow the language selector.  It now only feeds
``model_from_dev_id`` and the debug log.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, ROLE_SLAVE, is_inverter_dev_id, model_from_dev_id

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PREFIX = "g2-"
# Same glyph the official integration puts on its generated dashboard, so the
# two entries in the sidebar read as one product.
DASHBOARD_ICON = "mdi:home-battery"
# What earlier releases used; only rewritten by :func:`_async_sync_icon`.
_LEGACY_DASHBOARD_ICON = "mdi:solar-power-variant"

# url_paths whose stored title has already been inspected for a one-time
# migration.  Process-local on purpose: after a restart the check costs one
# storage read per device and is a no-op again once the title is the serial.
_TITLE_CHECKED: set[str] = set()

# url_paths whose view layout has already been inspected.  Same reasoning: one
# read per device per process, and nothing to do once upgraded.
_LAYOUT_CHECKED: set[str] = set()

# url_path -> the role whose view set has already been applied.  Deliberately
# keyed by the role and *not* by the layout revision (see ``_LAYOUT_VERSION``):
# the role arrives in ``event/state``, which the device publishes after Home
# Assistant has already written the dashboard, so a one-shot migration would run
# while the value is still unknown and never run again.  This memo lets the
# check be repeated on every setup and after every late state change, at the
# cost of one storage read each.
_ROLE_APPLIED: dict[str, str] = {}

# Config key holding the System view while a ``slave`` is not allowed to see it.
# It is put back verbatim when the unit reports another role again - a unit that
# is re-paired into a master/slave pair must get its tab back, and restoring the
# stored dict keeps every other view edit intact.
_ROLE_SYSTEM_KEY = "g2_role_system_view"

# Layout revision, stored next to ``views`` in ``.storage/lovelace.<url_path>``.
#
# It exists because the *structural* fingerprint below cannot notice a change
# that only touches card options: once a dashboard has the current view titles
# and view-level keys, ``_is_legacy_layout`` is False forever, so a release that
# only fixes axis scaling (removes the fixed ``span``) would never reach an
# existing install.  The marker lets such a release be applied while still
# leaving every user edit - renames, reordering, added cards - in place: the
# migration in ``_migrate_axis_cards`` rewrites individual card keys instead of
# replacing the whole layout.
#
#   1 (or absent)  charts carried a fixed `span`, so every axis was drawn at
#                  2 000 W / 2 500 W regardless of the measured maximum
#   2              axes scale to the data; `symmetric` / `stack` set per chart
#   3              a micro inverter's Control card no longer offers the TOU plan
#                  row - the firmware has no time-of-use feature at all
#   4              a micro inverter's System view gained the lifetime PV energy
#                  card next to "today"
#   5              a micro inverter's Device view put the power flow beside the
#                  alarm card instead of across the full width
#   6              that pair now share one row as a 3:1 split inside a single
#                  grid section - a nested grid card can only ever divide a row
#                  into equal halves, and two sibling sections are stacked as
#                  soon as the dashboard drops its ``max_columns``
#   7              that split now fills the whole row; revision 6's 9 + 3 was a
#                  correct 3:1 ratio but only a third of the row, so both cards
#                  came out small
#   8              the alarm card now references the entity the *registry* holds
#                  rather than a guessed id - an ``entity_id`` is derived from
#                  the device name at creation time, so a device renamed before
#                  the sensor existed produced ``sensor.wo_shi_..._active_alarms``
#                  and the card sat at "Alarm data unavailable" forever
#   9              a micro inverter's Device view no longer carries the
#                  「功率曲线」 (PV / grid / load) chart: the System view already
#                  draws those three series together, and on one unit the port
#                  chart plus the voltage / yield pair cover the tab
#   10             a micro inverter's Control card no longer pins
#                  ``entities.output_power`` to ``number.<dev>``: the firmware
#                  names both `number` entities after the device, so the base id
#                  is whichever HA created first (`output_power` on a two-input
#                  HiFlow Pro, `power_ctrl` on a single-input HiFlow) and the pin
#                  handed one row the other's range
#   11             every view dropped the ``<model> · <family>`` heading card.
#                  The text was generated in Python, so it could not follow the
#                  dashboard language selector and read 微型逆变器 inside an
#                  English UI; the view's own tab header already says which
#                  device the dashboard belongs to
#   12             the lifetime PV gauge uses the vendor app's "All" ring icon
#                  instead of ♾️, which read as "infinite power" rather than
#                  "everything generated so far"
#   13             the gauge tiles use the vendor app's own named icons
#                  (``panel`` / ``battery`` / ``cycle``) instead of emoji, so the
#                  same four tiles match the official cards glyph for glyph
#   14             the three tabs carry the vendor app's own icons
#                  (``mdi:home-analytics`` / ``mdi:home-battery`` / ``mdi:tune``)
#                  instead of a solar-panel set, and the dashboard's sidebar
#                  entry uses ``mdi:home-battery``
#   15             a micro inverter's Device view keeps the alarm card for the
#                  alarms themselves only: while the device reports none it
#                  hides and the schematic takes the whole row, carrying a small
#                  green-tick / red-lamp badge in its corner instead.  The System
#                  view also gained 「发电量」: one bar per day (or per month),
#                  with this-month / this-year / lifetime tiles above it
#   16             that energy card opens on a month, not on a day - revision 15
#                  wrote the day range the power charts use, which draws a single
#                  curve where the card exists to show one bar per day
#   17             role gating (protocol §32 ``event/state``): a unit whose role
#                  is ``slave`` gets no System view at all - the document limits
#                  ``system/state`` and every aggregate derived from it to
#                  「主机和单机」, so a follower's System tab was four gauges and
#                  two charts of nothing.  Its Control card also loses the rows
#                  whose command topics the same table restricts: EMS mode, the
#                  power-control lease, the output limit, the per-phase limit
#                  and the TOU plan.  A role that has not been heard yet (and
#                  ``single`` / ``master``) keeps the full layout
#   18             a micro inverter's Device row splits 50/50 once the device is
#                  alarming, the way the vendor app lays out that page: the
#                  schematic on one side and the fault list on the other.  It
#                  was 3:1, which gave a two-line alarm list a ninth of the row
#                  and the schematic three quarters it no longer needs while a
#                  fault is on screen.  With no alarm the list still hides and
#                  the schematic is centred across the whole row
#   19             that 50/50 pair really does fill the page.  Revision 18 wrote
#                  18 + 18 columns, but the section owns 48 of them, so both
#                  cards came out at 503 px inside a 1354 px row with a blank
#                  strip down the right; 24 + 24 is the same halves of the row
#                  the page actually has.  The schematic also lost its fixed
#                  640 px drawing cap - it now fills whatever cell it is given,
#                  scaling proportionally, instead of floating centred inside a
#                  cell it can never reach
#   20             the opt-in cards point at the real entity.  Revision 19 built
#                  them from the sensor *description key*, which only matches
#                  the entity id when the display name slugifies to that key
#                  too - so 「有功功率」 referenced
#                  ``sensor.<slug>_grid_on_power_5m``, an entity that has never
#                  existed (the sensor is named "Grid On Power (5 min)" and
#                  therefore lives at ``..._grid_on_power_5_min``).  The card
#                  drew an empty axis forever.  Every opt-in card is now
#                  resolved through the entity registry by ``unique_id``, and
#                  the stored ones are re-pointed here
#   21             the Device view of a micro inverter carries a 「更多曲线」 card
#                  with one switch per opt-in chart, so they can be turned on
#                  and off from the page they appear on instead of from
#                  *Settings -> Devices & Services -> Configure*.  The card
#                  writes the same dashboard document the Options Flow does,
#                  through the integration's own services
#   22             that card is called 「更多数据」, not 「更多曲线」: it switches
#                  readings (grid current, frequency, RSSI, ...), only some of
#                  which are curves the page already draws, and the readings it
#                  adds are chart cards the user picks from data, not from
#                  curves.  The stored title is rewritten for every dashboard
#                  that still carries the old one
_LAYOUT_KEY = "g2_layout"
_LAYOUT_VERSION = 22

# The view titles an earlier release wrote.  Used together with the absence of
# ``icon`` / ``max_columns`` as the fingerprint of an untouched old dashboard, so
# a layout upgrade can never overwrite a dashboard the user has edited.
_LEGACY_VIEW_TITLES: tuple[str, ...] = (
    "系统 / System",
    "设备 / Device",
    "控制 / Control",
)

# The history chart card type, referenced by the axis migration below.
HISTORY_CARD = "custom:hoymiles-g2-history-chart"
# The control card type, referenced by the TOU migration below.
CONTROL_CARD = "custom:hoymiles-g2-control"
# The gauge tile type, referenced by the icon migration below.
GAUGE_CARD = "custom:hoymiles-g2-gauge"
# The power flow and alarm card types, referenced by the Device view rebuild.
POWER_FLOW_CARD = "custom:hoymiles-g2-power-flow"
ALARM_CARD = "custom:hoymiles-g2-alarm"
# The opt-in chart switch card, added to the Device view of a micro inverter.
CHART_OPTIONS_CARD = "custom:hoymiles-g2-chart-options"
# The title that switch card was written with before revision 22.  Kept so a
# migration can tell "the title this release wrote" from "a title the user
# typed", and rewrite only the former.
_LEGACY_CHART_OPTIONS_TITLES: tuple[dict[str, str], ...] = (
    {"en": "More Curves", "zh": "更多曲线"},
)

# The two cards a micro inverter's Device view puts in its first row.  They are
# *siblings in one grid section*, sized 24 + 24 columns: a grid section divides
# itself into ``12 * column_span`` columns (``--base-column-count: 12`` in
# ``hui-grid-section``), so a ``column_span: 4`` section owns 48 of them, and
# 24 + 24 is an exact half-and-half split that stays on one row at every width.
# The three shapes that do not work, for the record:
#
#   * a nested ``grid`` card with ``columns: 2`` draws equal halves from the
#     *card* width rather than the section's, so it cannot be combined with
#     anything else and shrinks both children;
#   * two sibling *sections* with ``column_span: 3`` / ``1`` do give a 3:1
#     split, but the dashboard stacks sections once ``max_columns`` drops, so
#     the pair broke onto two rows on a narrower window.
#
# Revision 6 used 9 + 3 and revision 7 used 27 + 9, both of them 3:1: a correct
# ratio for a schematic that only had to share a row with a list which was
# almost always empty.  Now that the list hides itself when the device is quiet
# and the schematic takes the whole row in that case, the split only *exists*
# while there is a fault to show - and then the vendor app's own page is a
# half-and-half pair.
#
# Revision 18 wrote 18 / 18, which was the right *ratio* on the wrong *total*:
# it summed to 36 of the section's 48 columns, so both cards measured 503 px
# inside a 1354 px row and left a 348 px blank strip down the right-hand side.
# 24 / 24 is the same halves of the row the section actually has.
_FLOW_COLUMNS = 24
_ALARM_COLUMNS = 24
_SECTION_COLUMNS = 48

# The schematic's own drawing cap, in pixels.  The Device view's card is half a
# wide row while a fault is listed beside it and the whole row when the list
# hides, so any *fixed* cap is wrong in one of the two states: 640 px left the
# drawing floating in a cell it could never fill (and, once the row was
# measured, in a card that was itself too narrow), and a larger fixed number
# would overflow the half it lives in.  ``0`` means "no cap": the card fills
# whatever cell it is given and the SVG scales proportionally with it, which is
# what makes the pair occupy the full page width in both states.  The System
# view's flows keep their own explicit width - they have no ``variant`` and are
# never touched by the migrations.
_DEVICE_FLOW_MAX_WIDTH = 0

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
    """True for a grid-tied micro inverter, decided by the serial's PID."""
    return is_inverter_dev_id(dev_id)


def _entity(dev_id: str, key: str) -> str:
    """Build the conventional entity id ``sensor.<slug>_<key>``.

    This is only a *guess*: it is what Home Assistant would derive for a sensor
    whose name slugifies to exactly ``key``.  It is right for most readings but
    wrong for any whose display name is not the key - ``grid_on_power_5m`` is
    named "Grid On Power (5 min)" and therefore lives at
    ``sensor.<slug>_grid_on_power_5_min``, and a user rename moves it anywhere.
    Anything that must *work* rather than merely look plausible goes through
    :func:`_resolve_entity` instead.
    """
    return f"sensor.{_slug(dev_id)}_{key}"


def _resolve_entity(hass: HomeAssistant, dev_id: str, key: str) -> str:
    """The real ``entity_id`` of this device's ``key`` sensor.

    Resolved through the entity registry by ``unique_id`` - which is built from
    the serial plus the description key and never follows a rename - because the
    conventional id is only a guess (see :func:`_entity`).  The guess is the
    fallback for a device whose platform has not registered the entity yet,
    which is the only case where nothing better exists.
    """
    wanted = f"{DOMAIN}_{dev_id}_{key}"

    try:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

        registry = er.async_get(hass)
    except Exception:  # noqa: BLE001 - a card is never worth breaking setup for
        registry = None

    if registry is not None:
        try:
            for entry in list(registry.entities.values()):
                if entry.unique_id == wanted and entry.entity_id:
                    return entry.entity_id
        except Exception:  # noqa: BLE001
            pass

    return _entity(dev_id, key)


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

    return model_from_dev_id(dev_id) or ""


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


def _alarm_entity_id(hass: HomeAssistant, dev_id: str) -> str:
    """The *real* ``entity_id`` of this device's alarm sensor.

    The alarm sensor declares ``_attr_has_entity_name``, so Home Assistant
    derives its ``entity_id`` from the **device name at the moment the entity is
    first created** and never revisits it afterwards.  That sensor is far newer
    than the rest of the platform, so on a device the user had already renamed
    (``卧室 RMI-4161A0209FF6``) it came out as
    ``sensor.wo_shi_rmi_4161a0209ff6_active_alarms`` while every other entity
    kept the serial-based id.  A dashboard that hard-codes
    ``sensor.<slug(dev_id)>_active_alarms`` therefore points at an entity that
    never existed, and the alarm card falls back to "Alarm data unavailable"
    even though the sensor is reporting perfectly well.

    ``unique_id`` is the stable identity here - it is built from the serial and
    never follows a rename - so the registry is searched by that first.  The
    conventional id is only the fallback, for a device whose entity has not been
    registered yet (the very first setup, before the platform is added).
    """
    wanted = f"{DOMAIN}_{dev_id}_active_alarms"

    try:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

        registry = er.async_get(hass)
    except Exception:  # noqa: BLE001 - a card is never worth breaking setup for
        registry = None

    if registry is not None:
        try:
            for entry in list(registry.entities.values()):
                if entry.unique_id == wanted and entry.entity_id:
                    return entry.entity_id
        except Exception:  # noqa: BLE001
            pass

    return _entity(dev_id, "active_alarms")


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
    hass: HomeAssistant,
    dev_id: str,
    pv_count: int | None = None,
    role: str | None = None,
) -> None:
    """Create the device's storage dashboard if it does not exist yet.

    Idempotent: a second call for the same device (or after a reload) is a
    no-op.  Every failure path logs a warning and returns, because a dashboard
    must never take down the integration.

    ``pv_count`` and the model name only affect dashboards created from scratch;
    an existing dashboard is left alone so user edits - including a rename -
    survive upgrades.

    ``role`` is the unit's role in its installation (protocol §32), or ``None``
    while ``event/state`` has not been heard from.  It decides whether this unit
    gets a System view at all; see :func:`_build_views`.
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
        # After the revision work, deliberately: a legacy rebuild replaces the
        # whole ``views`` list, so the role gate has to see the final one.
        await _async_sync_role(
            hass, dashboards[url_path], dev_id, url_path, role
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
        # An icon an older release generated is migrated the same way, and only
        # while it is still that exact icon: a user who picked their own keeps
        # it, and re-running this is a no-op.
        if (existing.get(CONF_ICON) or "") == _LEGACY_DASHBOARD_ICON:
            await _async_reicon(collection, existing, url_path)
        # The view set is the user's, but the role gate is not a preference: a
        # follower has no System data to draw.  Applied to whatever is stored.
        await _async_sync_role(
            hass, dashboard.LovelaceStorage(hass, existing), dev_id, url_path, role
        )
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
        await store.async_save(
            {
                "views": _build_views(
                    dev_id, pv_count, model, _alarm_entity_id(hass, dev_id)
                ),
                _LAYOUT_KEY: _LAYOUT_VERSION,
            }
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not save dashboard views for %s", dev_id, exc_info=True)
        try:
            await collection.async_delete_item(item["id"])
        except Exception:  # noqa: BLE001
            pass
        return

    # The view set above is always complete; the role decides what of it is
    # visible.  Done here as well as on the existing-dashboard path because a
    # fresh install usually has not seen ``event/state`` yet, and the sync has to
    # be able to run the moment it does (see ``async_sync_role``).
    await _async_sync_role(hass, store, dev_id, url_path, role)

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
            CONF_ICON,
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
            if (item.get(CONF_ICON) or "") == _LEGACY_DASHBOARD_ICON:
                await _async_reicon(hass, collection, item, url_path)
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


async def _async_reicon(
    hass: HomeAssistant,
    collection: Any,
    item: dict[str, Any],
    url_path: str,
) -> None:
    """Swap the dashboard entry's sidebar icon for ``DASHBOARD_ICON``.

    Only ever reached while the stored icon is exactly the one an earlier
    release generated, so a user-chosen icon is never overwritten, and running
    it again is a no-op.  The panel is re-registered afterwards because that is
    the only supported way to change the icon drawn in the sidebar.
    """
    try:
        from homeassistant.components.lovelace.const import CONF_ICON  # noqa: PLC0415

        await collection.async_update_item(item["id"], {CONF_ICON: DASHBOARD_ICON})
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not re-icon dashboard %s", url_path, exc_info=True)
        return

    _LOGGER.info("Migrated dashboard %s icon to %s", url_path, DASHBOARD_ICON)
    _sync_sidebar_title(hass, url_path, item.get("title") or url_path)


async def _async_find_store(hass: HomeAssistant, url_path: str) -> Any:
    """Return the ``LovelaceStorage`` of an existing dashboard, or ``None``.

    The live registry is preferred because it is the object the frontend reads:
    saving through a second ``LovelaceStorage`` for the same key would write the
    right file but leave the loaded copy in memory untouched until a restart.
    The collection is only consulted when the registry has no entry for the slug
    (a dashboard created by an earlier release, before the registry was
    populated in this process).
    """
    lovelace_data = hass.data.get("lovelace")
    dashboards = getattr(lovelace_data, "dashboards", None) if lovelace_data else None
    if isinstance(dashboards, dict):
        store = dashboards.get(url_path)
        if store is not None:
            return store

    try:
        from homeassistant.components.lovelace import dashboard  # noqa: PLC0415
        from homeassistant.components.lovelace.const import CONF_URL_PATH  # noqa: PLC0415

        collection = dashboard.DashboardsCollection(hass)
        await collection.async_load()
        for item in collection.async_items():
            if item.get(CONF_URL_PATH) == url_path:
                return dashboard.LovelaceStorage(hass, item)
    except Exception:  # noqa: BLE001 - a dashboard is never worth breaking setup
        _LOGGER.debug("Could not locate dashboard %s", url_path, exc_info=True)

    return None


async def async_sync_role(hass: HomeAssistant, dev_id: str, role: str | None) -> None:
    """Apply the unit's role to an already-created dashboard.

    Public because the role is not known at setup time: ``event/state`` is
    published by the device whenever it feels like it, and often *after* the
    dashboard was written.  The caller re-invokes this each time the role
    changes (at most a handful of times per install) and it is a no-op when
    nothing has to move.

    Never raises.  ``role is None`` means "not heard yet" and leaves the stored
    layout exactly as it is.
    """
    url_path = _url_path(dev_id)
    try:
        store = await _async_find_store(hass, url_path)
        if store is None:
            return
        await _async_sync_role(hass, store, dev_id, url_path, role)
    except Exception:  # noqa: BLE001 - never break setup for a tab
        _LOGGER.debug("Could not sync the role of %s", dev_id, exc_info=True)


async def _async_sync_role(
    hass: HomeAssistant,
    store: Any,
    dev_id: str,
    url_path: str,
    role: str | None,
) -> None:
    """Hide or restore the System view according to the unit's role.

    Protocol §32 makes the role the key to two different sets of topics, and the
    document puts ``system/state`` - and therefore every system aggregate - under
    「主机和单机」: a ``slave`` never publishes it.  Its System view was six cards
    of ``unknown``, so it is taken out of the stored config and kept aside under
    ``_ROLE_SYSTEM_KEY`` instead of being deleted.  Reporting another role again
    puts the very same dict back at the front, so re-pairing a unit restores its
    tab byte for byte - including anything the user changed inside it.

    Only ``slave`` is acted on.  ``None`` (no ``event/state`` yet, or a spelling
    this release does not know) keeps the full layout: "not heard from" is not
    "follows a master", and a follower's dashboard losing its first tab because
    MQTT was slow would be worse than the empty cards this fixes.

    Every write is a single ``async_save`` and the whole function is optional:
    the Control card gates its own rows from the ``system_role`` sensor, so a
    failure here costs the System tab only.
    """
    if role is None:
        return
    if _ROLE_APPLIED.get(url_path) == role:
        return

    try:
        config = await _async_read_storage(hass, store) or {}
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not read dashboard %s", url_path, exc_info=True)
        return

    if not isinstance(config, dict):
        return
    views = config.get("views")
    if not isinstance(views, list):
        return

    stashed = config.get(_ROLE_SYSTEM_KEY)
    updated: dict[str, Any] | None = None

    if role == ROLE_SLAVE:
        if isinstance(stashed, dict):
            # Hidden by an earlier run; the tab is already gone.
            _ROLE_APPLIED[url_path] = role
            return
        kept: list[Any] = []
        hidden: dict[str, Any] | None = None
        for view in views:
            if hidden is None and isinstance(view, dict) and view.get("path") == "system":
                hidden = view
                continue
            kept.append(view)
        if hidden is None:
            # No System view to hide (a hand-built dashboard): nothing to do,
            # and the role is recorded so this is not re-read on every update.
            _ROLE_APPLIED[url_path] = role
            return
        if not kept:
            # Refuse to leave a dashboard with no tabs at all.
            _LOGGER.debug("Not hiding the only view of %s", url_path)
            return
        updated = {**config, "views": kept, _ROLE_SYSTEM_KEY: hidden}
    else:
        if not isinstance(stashed, dict):
            _ROLE_APPLIED[url_path] = role
            return
        updated = {**config, "views": [stashed, *views]}
        updated.pop(_ROLE_SYSTEM_KEY, None)

    try:
        await store.async_save(updated)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not save dashboard %s", url_path, exc_info=True)
        return

    _ROLE_APPLIED[url_path] = role
    _LOGGER.info(
        "Dashboard %s: %s as role %s",
        url_path,
        "hid the System view" if role == ROLE_SLAVE else "restored the System view",
        role,
    )


async def _async_upgrade_layout(
    hass: HomeAssistant,
    store: Any,
    dev_id: str,
    url_path: str,
    pv_count: int | None,
    model: str,
) -> None:
    """Bring a dashboard written by an older release up to ``_LAYOUT_VERSION``.

    Two mechanisms, tried in order, because they protect different things:

    1. :func:`_is_legacy_layout` - the dashboard is byte-for-byte what an early
       release produced, so it is safe to rebuild it wholesale.
    2. :func:`_migrate_axis_cards` - the dashboard has been touched by the user
       (renamed views, extra cards), so only the *card options* this release
       changed are rewritten, one key at a time.  Renames, ordering and added
       cards are all preserved.

    Both are gated on the stored ``_LAYOUT_KEY`` marker, so a dashboard is
    migrated at most once and a user who deliberately re-adds a fixed ``span``
    afterwards keeps it.

    Verified once per device per process, because ``LovelaceStorage`` caches its
    config in memory.  The role gate is deliberately *not* applied here: a legacy
    rebuild replaces the whole ``views`` list, so the caller runs
    :func:`_async_sync_role` after this returns, never before.
    """
    if url_path in _LAYOUT_CHECKED:
        return
    _LAYOUT_CHECKED.add(url_path)

    try:
        config = await _async_read_storage(hass, store) or {}
    except Exception:  # noqa: BLE001 - a layout is never worth breaking setup for
        _LOGGER.warning("Could not read dashboard %s", url_path, exc_info=True)
        return

    if not isinstance(config, dict):
        return

    # Already at this revision: nothing to do, now or after a restart.
    if config.get(_LAYOUT_KEY) == _LAYOUT_VERSION:
        return

    if _is_legacy_layout(config):
        try:
            await store.async_save(
                {
                    "views": _build_views(
                        dev_id, pv_count, model, _alarm_entity_id(hass, dev_id)
                    ),
                    _LAYOUT_KEY: _LAYOUT_VERSION,
                }
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not upgrade dashboard %s", url_path, exc_info=True)
            return
        _LOGGER.info("Rebuilt dashboard %s at layout revision %s", url_path, _LAYOUT_VERSION)
        return

    # A dashboard the user has touched: patch the chart options in place.
    try:
        alarm_entity = _alarm_entity_id(hass, dev_id) if _is_inverter(dev_id) else None
        changed = _migrate_axis_cards(config)
        changed = _migrate_control_cards(config, dev_id) or changed
        changed = _migrate_energy_total_card(config, dev_id) or changed
        changed = _migrate_device_alarm_card(config, dev_id, alarm_entity) or changed
        changed = (
            _migrate_device_alarm_columns(config, dev_id, alarm_entity) or changed
        )
        changed = _migrate_device_drop_total_power(config, dev_id) or changed
        changed = _migrate_system_energy_chart(config, dev_id) or changed
        changed = _migrate_drop_heading(config) or changed
        changed = _migrate_total_icon(config, dev_id) or changed
        changed = _migrate_gauge_icons(config) or changed
        changed = _migrate_view_icons(config) or changed
        changed = _migrate_optional_entities(config, hass, dev_id) or changed
        changed = _migrate_chart_options_card(config, dev_id) or changed
        changed = _migrate_chart_options_title(config) or changed
        if not changed:
            # Nothing matched, so the dashboard is not one of ours at the
            # revision being migrated (a hand-built dashboard, or a layout from
            # a much newer release).  Record the revision so this check does not
            # run again, but leave the content alone.
            await store.async_save({**config, _LAYOUT_KEY: _LAYOUT_VERSION})
            return
        await store.async_save({**config, _LAYOUT_KEY: _LAYOUT_VERSION})
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not patch dashboard %s", url_path, exc_info=True)
        return

    _LOGGER.info("Migrated dashboard %s to layout revision %s", url_path, _LAYOUT_VERSION)


def _migrate_control_cards(config: dict[str, Any], dev_id: str) -> bool:
    """Drop the TOU plan row from a micro inverter's Control card.

    An earlier release created the ``tou_*`` entities on every model, so the
    Control card of a micro inverter grew a "Get TOU plan" row - a button that
    could only ever time out, because the firmware neither declares ``tou_get``
    nor publishes a ``tou_*`` topic.  The generator no longer emits that row, and
    the sensor platform now prunes the entities themselves; this migration exists
    for the dashboards already stored on disk, whose ``_LAYOUT_KEY`` marker keeps
    :func:`_build_views` from regenerating them.

    Only a card that really is the inverter layout is touched: the storage unit
    keeps its TOU editor, and its Control card is left byte-for-byte alone.  A
    dashboard where the row was re-enabled by hand is not overridden either - the
    key is only written where it is still absent.

    The ``entities.output_power`` pin an older release wrote is removed here as
    well, for the same reason it is no longer generated: ``number.<dev>`` is
    whichever of the two ``number`` entities Home Assistant created first, so
    the pin is right on a two-input HiFlow Pro and wrong on a single-input
    HiFlow.  The card now separates the two by their declared floor.
    """
    if not _is_inverter(dev_id):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    changed = False
    for card in _walk_cards(views):
        if not isinstance(card, dict):
            continue
        if card.get("type") != CONTROL_CARD:
            continue
        pins = card.get("entities")
        if isinstance(pins, dict) and "output_power" in pins:
            pins = {k: v for k, v in pins.items() if k != "output_power"}
            if pins:
                card["entities"] = pins
            else:
                card.pop("entities", None)
            changed = True
        if "show_tou" in card:
            continue
        card["show_tou"] = False
        changed = True

    return changed


def _migrate_energy_total_card(config: dict[str, Any], dev_id: str) -> bool:
    """Add the lifetime PV energy card next to "today" on an existing dashboard.

    The System view already shows a "PV today" gauge; this release puts the
    lifetime counter beside it so the two can be read together.  A dashboard
    stored by an older release is not regenerated - ``_LAYOUT_KEY`` short-circuits
    :func:`_build_views` - so the card has to be inserted into the live layout.

    Insertion is positional and conservative:

    * the anchor is the card whose ``entity`` is exactly
      ``sensor.<slug>_system_pv_energy_today``, never a title or an index, so a
      user who renamed or reordered things still gets the card in the right
      place;
    * the new card is only added where the layout has no ``pv_energy_total``
      gauge yet, which makes the migration idempotent and keeps a card the user
      removed from coming back;
    * only micro inverters are touched, because ``pv_energy_total`` is created
      with ``requires_absent=CAP_SYSTEM_STATE`` and does not exist on a storage
      unit.
    """
    if not _is_inverter(dev_id):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    today_entity = _entity(dev_id, "system_pv_energy_today")
    total_entity = _entity(dev_id, "pv_energy_total")

    # Never add the card twice: an install that has been through this migration
    # already (or was generated fresh) must be left alone.
    for card in _walk_cards(views):
        if isinstance(card, dict) and card.get("entity") == total_entity:
            return False

    added = False

    def walk(node: Any) -> None:
        nonlocal added
        if added:
            return
        if isinstance(node, list):
            for index, item in enumerate(node):
                if added:
                    return
                # The anchor lives in a ``cards`` list; splice right after it, so
                # the new card lands immediately to its right.
                if isinstance(item, dict) and item.get("entity") == today_entity:
                    node.insert(index + 1, _energy_total_gauge(dev_id))
                    added = True
                    return
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("cards", "sections"):
            if isinstance(node.get(key), list):
                walk(node[key])

    walk(views)
    return added


def _migrate_device_alarm_card(
    config: dict[str, Any], dev_id: str, alarm_entity: str | None = None
) -> bool:
    """Put the alarm card beside a narrower power flow on an existing dashboard.

    The Device view used to draw the power flow across the full width, with the
    alarm list appearing nowhere.  This release gives the flow only one of the
    two columns and puts the alarms in the other, so the two read together: a
    fault and the schematic it affects are on the same screen instead of one tab
    apart.

    The rebuild is narrow on purpose:

    * only the **inverter** layout is touched - a storage unit's Device view has
      a battery card and no ``alarm_state`` capability at all, so an alarm card
      there would sit at "unavailable" forever;
    * only a power-flow card carrying ``variant: inverter`` is an anchor; a
      user-added flow elsewhere on the page is left alone;
    * the card is only added where the layout has no alarm card yet, which makes
      the migration idempotent and keeps a card the user deleted from returning;
    * ``max_width`` is only lowered where it is still the old full-width value,
      so a width the user chose deliberately is preserved.
    """
    if not _is_inverter(dev_id):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    # Already there (a fresh layout, or an install that has run this migration):
    # the card must not come back, and the width is left as found.
    if any(
        isinstance(card, dict) and card.get("type") == ALARM_CARD
        for card in _walk_cards(views)
    ):
        return False

    changed = False

    def _is_inverter_flow(item: Any) -> bool:
        return (
            isinstance(item, dict)
            and item.get("type") == POWER_FLOW_CARD
            and item.get("variant") == "inverter"
        )

    def _narrow_flow(flow: dict[str, Any]) -> bool:
        """Give the flow one column and a width that fits it."""
        touched = False
        # ``grid_options: {columns: full}`` is what made the card span the
        # section; dropped so it takes one column of the two-column grid it is
        # about to live in.
        if flow.pop("grid_options", None) is not None:
            touched = True
        if flow.get("max_width") in (640, 700):
            # The same width revision 19 settles on; written here as well so a
            # dashboard coming all the way from revision 5 never flashes the
            # full-width value before ``_migrate_device_alarm_columns`` runs.
            flow["max_width"] = _DEVICE_FLOW_MAX_WIDTH
            touched = True
        return touched

    def _process(container: dict[str, Any], key: str) -> bool:
        """Rewrite the card list ``container[key]``; True if anything changed."""
        nonlocal changed
        cards = container.get(key)
        if not isinstance(cards, list):
            return False

        for index, item in enumerate(cards):
            if not _is_inverter_flow(item):
                continue

            changed = _narrow_flow(item) or changed
            # A two-column grid already places cards side by side: the alarm
            # card only has to be inserted next to the flow.
            if container.get("columns") == 2:
                cards.insert(index + 1, _alarm_card(dev_id, alarm_entity))
            else:
                # A full-width section stacks its cards, so the pair has to be
                # wrapped to end up beside each other.
                cards[index] = _subgrid([item, _alarm_card(dev_id, alarm_entity)])
            changed = True
            return True
        return False

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        for key in ("cards", "sections"):
            if _process(node, key):
                return
        for key in ("cards", "sections"):
            if isinstance(node.get(key), list):
                walk(node[key])

    walk(views)
    return changed


def _migrate_device_alarm_columns(
    config: dict[str, Any], dev_id: str, alarm_entity: str | None = None
) -> bool:
    """Put the schematic and the alarms on one row as a 3:1 pair; revision 6.

    Revision 5 placed the power flow and the alarm list inside a nested ``grid``
    card with ``columns: 2``.  A nested grid only ever divides its row into
    *equal* columns - measured on a live dashboard at 431 px + 431 px inside an
    870 px row - which left the schematic too small to read, and it offers no
    way to ask for anything else.

    Revision 6 therefore makes the two cards *plain siblings of one grid
    section*, sized 9 and 3.  A grid section subdivides itself into
    ``12 * column_span`` columns (``--base-column-count: 12`` in
    ``hui-grid-section``), so 9 + 3 is an exact 3:1 split that stays on a single
    row at every width - unlike two sibling *sections*, which the dashboard
    stacks once it drops its ``max_columns``.

    Revision 7 keeps that shape but scales it up to the section's whole internal
    grid: a section lays out ``12 * column_span`` columns, so on a desktop that
    fits three dashboard columns it owns 36 of them.  9 + 3 was 3:1 but filled
    only a third of the row and left the schematic needlessly small, while
    27 + 9 fills all 36 columns and is still exactly 3:1.

    Revision 18 keeps filling those 36 columns but splits them in half: once the
    alarm list hides itself when the device is quiet, the pair only appears
    while there really is a fault, and the vendor app lays that page out as two
    equal halves.  18 + 18 is that page; the schematic reclaims the whole row on
    its own when the list is gone (see ``_syncRowSpan`` in the card).

    The rewrite is canonical rather than incremental: the flow and the alarm are
    located wherever an earlier revision left them (inside a nested grid, in a
    section of its own, or already side by side) and the section is then
    rewritten to the shape this revision wants.  A second run is therefore a
    no-op.  A flow the user placed among cards of their own keeps its place and
    is left alone.
    """
    if not _is_inverter(dev_id):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    changed = False

    def _is_flow(item: Any) -> bool:
        return (
            isinstance(item, dict)
            and item.get("type") == POWER_FLOW_CARD
            and item.get("variant") == "inverter"
        )

    def _is_alarm(item: Any) -> bool:
        return isinstance(item, dict) and item.get("type") == ALARM_CARD

    def _flatten(section: dict[str, Any]) -> None:
        """Lift a nested grid's cards up into the section that held it."""
        nonlocal changed
        cards = section.get("cards")
        if not isinstance(cards, list):
            return
        flat: list[Any] = []
        lifted = False
        for card in cards:
            inner = card.get("cards") if isinstance(card, dict) else None
            if (
                isinstance(card, dict)
                and card.get("type") == "grid"
                and isinstance(inner, list)
                and any(_is_flow(entry) or _is_alarm(entry) for entry in inner)
            ):
                flat.extend(inner)
                lifted = True
            else:
                flat.append(card)
        if lifted:
            section["cards"] = flat
            changed = True

    for view in views:
        if not isinstance(view, dict):
            continue
        sections = view.get("sections")
        if not isinstance(sections, list):
            continue

        for section in sections:
            if isinstance(section, dict):
                _flatten(section)

        flow: Any = None
        flow_section: Any = None
        alarm: Any = None
        alarm_only: list[dict[str, Any]] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            cards = section.get("cards")
            if not isinstance(cards, list):
                continue
            for card in cards:
                if flow is None and _is_flow(card):
                    flow, flow_section = card, section
                elif alarm is None and _is_alarm(card):
                    alarm = card
            if cards and all(_is_alarm(card) for card in cards):
                alarm_only.append(section)

        if flow is None or not isinstance(flow_section, dict):
            continue

        section_cards = flow_section.get("cards")
        if not isinstance(section_cards, list):
            continue
        # A flow the user placed among cards of their own keeps its position.
        if any(not (_is_flow(card) or _is_alarm(card)) for card in section_cards):
            continue

        if alarm is None:
            alarm = _alarm_card(dev_id, alarm_entity)
            changed = True

        # The sensor derives its ``entity_id`` from the device name at creation
        # time, so a rename can move it away from the serial-based spelling the
        # card was written with.  Only an id this integration would itself have
        # generated is replaced - a card pointing somewhere the user chose is
        # left alone.
        if alarm_entity and alarm.get("entity") != alarm_entity:
            current = alarm.get("entity")
            if current == _entity(dev_id, "active_alarms") or not current:
                alarm["entity"] = alarm_entity
                changed = True

        # ``max_width`` was halved for the half-width column revision 5 drew;
        # revision 6 put it back to 700, revision 7 widened it to 1100 for the
        # three-quarter cell, and revision 19 settles on ``0`` - "fill the
        # cell" - now that the pair really does split the row in half.  Only
        # the values earlier revisions wrote are replaced - a width the user
        # chose is kept.
        if flow.get("max_width") in (380, 640, 700, 1100):
            flow["max_width"] = _DEVICE_FLOW_MAX_WIDTH
            changed = True
        # Both cards are now sized in columns of the shared section.
        if flow.get("grid_options") != {"columns": _FLOW_COLUMNS}:
            flow["grid_options"] = {"columns": _FLOW_COLUMNS}
            changed = True
        if alarm.get("grid_options") != {"columns": _ALARM_COLUMNS}:
            alarm["grid_options"] = {"columns": _ALARM_COLUMNS}
            changed = True

        # Revision 15 stops reserving a quarter of the row for a list that is
        # empty most of the time: the alarm card hides itself and the schematic
        # widens over the freed columns, so it must be able to count what it is
        # hiding.  Both keys are written only when absent or wrong, which keeps
        # a second run a no-op.
        if alarm.get("only_when_alarm") is not True:
            alarm["only_when_alarm"] = True
            changed = True
        if alarm_entity and flow.get("alarm_entity") != alarm_entity:
            flow["alarm_entity"] = alarm_entity
            changed = True
        elif not alarm_entity and "alarm_entity" in flow:
            # A stale id would make the badge show a red lamp for a device the
            # integration no longer tracks; a missing one just drops the badge.
            flow.pop("alarm_entity", None)
            changed = True

        wanted = [flow, alarm]
        if section_cards != wanted:
            flow_section["cards"] = wanted
            changed = True
        # The pair lives in the full-width section the row has always used.
        if flow_section.get("column_span", 4) != 4:
            flow_section["column_span"] = 4
            changed = True

        # Any alarm-only section is a leftover of revision 6's first draft;
        # dropping it keeps the result canonical.
        for section in alarm_only:
            if section is not flow_section:
                sections.remove(section)
                changed = True

    return changed


def _migrate_device_drop_total_power(config: dict[str, Any], dev_id: str) -> bool:
    """Remove the 「功率曲线」 chart from a micro inverter's Device view; rev. 9.

    Revision 9 stops generating that card.  The three series it drew
    (``system_pv_power`` / ``system_grid_power`` / ``system_load_power``) are
    still drawn together on the **System** view, where they belong: that tab is
    the installation as a whole.  On the Device tab they answered a question
    nobody asks of a single unit, duplicated what the per-port chart above
    already says, and meant storing the same three series twice per device.

    The rewrite is deliberately narrow and idempotent:

    * only the **inverter** layout is touched - the storage unit's Device view
      never had this card;
    * a card is recognised by its *series*, not by its title: the user is free
      to rename a card, and a chart that happens to be called 功率曲线 but plots
      something else must survive;
    * the chart has to be alone in its own grid section, which is how every
      generated layout placed it - a chart the user dragged next to cards of
      their own is left in place rather than taking those cards with it;
    * a section that is left empty is dropped, so no blank row remains.

    A second run finds nothing to remove and returns ``False``, which is what
    keeps the ``_LAYOUT_KEY`` marker honest.
    """
    if not _is_inverter(dev_id):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    wanted = {
        _entity(dev_id, "system_pv_power"),
        _entity(dev_id, "system_grid_power"),
        _entity(dev_id, "system_load_power"),
    }

    def _is_total_power(card: Any) -> bool:
        if not isinstance(card, dict) or card.get("type") != HISTORY_CARD:
            return False
        return set(_series_entities(card)) == wanted

    changed = False
    for view in views:
        if not isinstance(view, dict) or view.get("path") != "device":
            continue
        sections = view.get("sections")
        if not isinstance(sections, list):
            continue
        for section in list(sections):
            if not isinstance(section, dict):
                continue
            cards = section.get("cards")
            if not isinstance(cards, list):
                continue
            if len(cards) != 1 or not _is_total_power(cards[0]):
                continue
            sections.remove(section)
            changed = True

    return changed


def _migrate_system_energy_chart(config: dict[str, Any], dev_id: str) -> bool:
    """Add 「发电量」 to an existing dashboard's System view; rev. 15.

    Revision 15 generates a bar chart of the lifetime PV counter (one bar per
    day of a month, one per month of a year) with three tiles above it, so the
    tab answers "how much did it make" and not only "how much is it making".
    ``_LAYOUT_KEY`` short-circuits :func:`_build_views`, so an install that
    already has a dashboard never sees the new card without this.

    The rewrite is conservative and idempotent:

    * only the **inverter** layout is touched - ``pv_energy_total`` is created
      with ``requires_absent=CAP_SYSTEM_STATE`` and does not exist on a storage
      unit, so the card there would read "no data" for ever;
    * the anchor is the ``chart`` that plots exactly the three system power
      series - not a title and not an index - so a user who renamed or
      reordered cards still gets the new chart in the right place.  The card is
      inserted as a **sibling section** after the anchor's section, which is how
      :func:`_build_inverter_views` lays the tab out, and reproduced here rather
      than appending to the anchor's ``cards`` because that section is
      ``full``-column and would stack them;
    * the migration returns ``False`` when there is nothing left to change, so a
      second run is a no-op and a chart the user deliberately deleted stays
      deleted.

    Revision 16 only repairs the opening ``range`` of the card this function
    inserts: revision 15 wrote it as a *day*, which is a curve of one day and
    not the row of bars the card exists for.  Only the exact value revision 15
    wrote is replaced, so a user who set another range keeps it.
    """
    if not _is_inverter(dev_id):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    energy_entity = _entity(dev_id, "pv_energy_total")
    power_entities = {
        _entity(dev_id, "system_pv_power"),
        _entity(dev_id, "system_grid_power"),
        _entity(dev_id, "system_load_power"),
    }

    # Already present (fresh layout, or an install that ran this before): the
    # card must not come back, but a range revision 15 got wrong is repaired.
    for card in _walk_cards(views):
        if (
            isinstance(card, dict)
            and card.get("type") == HISTORY_CARD
            and energy_entity in _series_entities(card)
        ):
            if card.get("range") == "day":
                card["range"] = "month"
                return True
            return False

    def _is_system_power(card: Any) -> bool:
        return (
            isinstance(card, dict)
            and card.get("type") == HISTORY_CARD
            and power_entities.issubset(set(_series_entities(card)))
        )

    def _energy_chart() -> dict[str, Any]:
        return _grid(
            [
                _history(
                    _t("PV Energy", "发电量"),
                    [
                        {
                            "entity": energy_entity,
                            "name": _t("Generation", "发电量"),
                            "color": "#22c55e",
                        }
                    ],
                    unit="kWh",
                    height=300,
                    range="month",
                    sync_group=f"{_slug(dev_id)}-energy",
                    symmetric=False,
                    stack=False,
                    mode="auto",
                    show_totals=True,
                    scale=0.001,
                )
            ]
        )

    for view in views:
        if not isinstance(view, dict) or view.get("path") != "system":
            continue
        sections = view.get("sections")
        if not isinstance(sections, list):
            continue
        for index, section in enumerate(sections):
            cards = section.get("cards") if isinstance(section, dict) else None
            if not isinstance(cards, list):
                continue
            if not any(_is_system_power(card) for card in cards):
                continue
            sections.insert(index + 1, _energy_chart())
            return True

    return False


def _migrate_drop_heading(config: dict[str, Any]) -> bool:
    """Remove the ``<model> · <family>`` heading card from every view; rev. 11.

    Revision 11 stops generating that card.  The text was assembled in Python
    (``HiFlow Pro · 微型逆变器``), so it was frozen in whatever language the
    integration happened to hardcode and read 微型逆变器 even in an English or
    German UI - the one string on the dashboard the language selector could not
    reach.  It also said nothing the view's own tab header does not already say,
    and it cost the first row of every tab.

    Recognition is deliberately narrow so a heading the user added themselves
    survives:

    * only ``type: heading`` cards are considered;
    * a heading is removed when its text is one of the two family labels this
      generator wrote, with or without a model prefix - exactly the text the
      generator used to emit.

    Removal is by identity of the dict, so the card disappears from the grid it
    sits in and the section itself stays - the remaining cards keep their
    position.  A second run finds nothing and returns ``False``, which is what
    keeps the ``_LAYOUT_KEY`` marker honest.
    """
    views = config.get("views")
    if not isinstance(views, list):
        return False

    # Every family label the generator used to print, prefixed or bare.
    family: tuple[str, ...] = ("微型逆变器", "储能系统")

    def _is_ours(card: Any) -> bool:
        if not isinstance(card, dict) or card.get("type") != "heading":
            return False
        text = str(card.get("heading") or "").strip()
        # Bare label, or ``<model> · <label>`` - a bare serial, "HiFlow Pro",
        # anything the firmware reports.
        return any(
            text == label or text.endswith(f"· {label}") for label in family
        )

    changed = False
    emptied: list[Any] = []

    def _strip(cards: list[Any]) -> None:
        nonlocal changed
        dropped = False
        for card in list(cards):
            if _is_ours(card):
                cards.remove(card)
                changed = True
                dropped = True
        if dropped and not cards:
            emptied.append(cards)

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("cards", "sections"):
            children = node.get(key)
            if isinstance(children, list):
                if key == "cards":
                    _strip(children)
                walk(children)

    walk(views)

    # A section that held nothing but the heading would leave an empty row
    # behind.  Only a section this migration emptied is dropped - a section the
    # user emptied themselves is left exactly as they left it.
    for view in views:
        if not isinstance(view, dict):
            continue
        sections = view.get("sections")
        if not isinstance(sections, list):
            continue
        for section in list(sections):
            if not isinstance(section, dict):
                continue
            cards = section.get("cards")
            if isinstance(cards, list) and any(cards is e for e in emptied):
                sections.remove(section)
                changed = True

    return changed


def _migrate_total_icon(config: dict[str, Any], dev_id: str) -> bool:
    """Swap the lifetime PV gauge's ♾️ for the vendor app's "All" ring; rev. 12.

    Only the one card is touched, and only when it still carries the icon this
    generator used to write.  The anchor is the card's ``entity`` - the
    serial-derived ``sensor.<slug>_pv_energy_total`` - never a title or an index,
    so a dashboard the user reorganised is still patched in the right place.

    An icon the user picked themselves is left alone: the replacement is gated on
    the old value, so ``icon: ❤️`` and a card with no ``icon`` key both survive.
    A second run finds nothing and returns ``False``.
    """
    if not _is_inverter(dev_id):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    total_entity = _entity(dev_id, "pv_energy_total")
    changed = False

    for card in _walk_cards(views):
        if not isinstance(card, dict):
            continue
        if card.get("entity") != total_entity:
            continue
        if card.get("icon") != "♾️":
            continue
        card["icon"] = "all"
        changed = True

    return changed


def _migrate_gauge_icons(config: dict[str, Any]) -> bool:
    """Swap the emoji gauge icons for the vendor app's named ones; rev. 13.

    The four System tiles used to carry an emoji (``☀️`` / ``⚡`` / ``🔋``).  The
    official cards draw their own vector set instead, so the same four tiles on
    the same dashboard looked like two different products.  The card now
    understands those names (see ``ICON_SVG`` in ``hoymiles-g2-gauge.js``), and
    this rewrites the dashboards already on disk.

    Gated on the old value, so an icon the user picked themselves survives, and
    a second run finds nothing and returns ``False``.  Only gauge cards are
    touched: the same emoji appear in titles and on other cards, and those are
    plain text there.
    """
    views = config.get("views")
    if not isinstance(views, list):
        return False

    # Emoji the generator used to write, mapped to the name that replaces it.
    swap = {"☀️": "panel", "⚡": "battery", "🔋": "cycle"}
    changed = False

    for card in _walk_cards(views):
        if not isinstance(card, dict):
            continue
        if card.get("type") != GAUGE_CARD:
            continue
        icon = card.get("icon")
        if icon not in swap:
            continue
        # The SOC tile is a level, not a flow, so it keeps the battery shell
        # rather than the discharge ring the "🔋" would otherwise become.
        entity = str(card.get("entity") or "")
        card["icon"] = "battery" if entity.endswith("_soc") else swap[icon]
        changed = True

    return changed


def _migrate_view_icons(config: dict[str, Any]) -> bool:
    """Give the view tabs the icons the vendor app uses; rev. 14.

    An earlier release drew ``mdi:solar-power-variant`` on System and
    ``mdi:solar-panel-large`` on Device, while the official dashboard uses
    ``mdi:home-analytics`` and ``mdi:home-battery``.  The same three tabs side
    by side therefore carried different glyphs.  Only the exact old values are
    rewritten, so a tab the user re-iconed keeps its icon, and a second run
    finds nothing.
    """
    views = config.get("views")
    if not isinstance(views, list):
        return False

    changed = False
    for view in views:
        if not isinstance(view, dict):
            continue
        # The view's `path` is what `_VIEW_ICONS` is keyed on; a view without one
        # was not generated by us (the first view has an empty path, which is
        # why this looks the icon up rather than defaulting it).
        key = view.get("path")
        wanted = _VIEW_ICONS.get(key) if isinstance(key, str) else None
        if wanted is None:
            continue
        if view.get("icon") != _LEGACY_VIEW_ICONS.get(key):
            continue
        view["icon"] = wanted
        changed = True

    return changed


def _migrate_optional_entities(
    config: dict[str, Any], hass: HomeAssistant, dev_id: str
) -> bool:
    """Re-point stored opt-in cards at the real entity; rev. 20.

    An older release built each of these cards from the sensor *description
    key* - ``sensor.<slug>_<key>`` - which is only the real entity id when the
    sensor's display name slugifies to that key too.  ``grid_on_power_5m`` is
    named "Grid On Power (5 min)" and therefore lives at
    ``..._grid_on_power_5_min``, so 「有功功率」 pointed at an entity that has
    never existed and the card stayed empty.  The user's own rename does the
    same thing.

    Each card is resolved by ``unique_id`` instead, which survives both a
    rename and the display-name mismatch.  Only opted-in cards are touched, and
    only their series entity, so ``since``, titles, colours and axis limits are
    kept.  A card that already names the right entity is left as it is, which is
    what makes a second run a no-op.
    """
    views = config.get("views")
    if not isinstance(views, list):
        return False

    changed = False
    for card in _walk_cards(views):
        if not isinstance(card, dict):
            continue
        key = card.get(_OPTIONAL_KEY)
        if key not in OPTIONAL_CHARTS:
            continue
        entity = _resolve_entity(hass, dev_id, OPTIONAL_CHARTS[key]["entity"])
        changed = _repoint_card(card, entity) or changed

    return changed


def _migrate_axis_cards(config: dict[str, Any]) -> bool:
    """Rewrite the chart config this release changed; return True if any did.

    Only three things are touched, and each only when it still carries the value
    an older release wrote:

    * a fixed ``span`` on a history chart is dropped, so the y axis scales to
      the measured maximum instead of being pinned to 2 000 W / 2 500 W;
    * ``symmetric`` is set to ``False`` on a chart whose series are all
      non-negative levels (voltage, energy, PV power) - a mirrored axis halves
      the usable height for such data;
    * ``stack`` is set to ``False`` where the series are independent
      measurements rather than additive parts of one total.

    Everything else - titles, colours, heights, series order, extra cards, view
    names - is left exactly as found, which is what makes this safe to run on a
    dashboard the user has edited.
    """
    views = config.get("views")
    if not isinstance(views, list):
        return False

    changed = False
    for card in _walk_cards(views):
        if not isinstance(card, dict):
            continue
        if card.get("type") != HISTORY_CARD:
            continue

        # 1. A fixed half-range is what pinned every axis.  Removing it is the
        #    whole point of this migration, so it goes unconditionally.
        if "span" in card:
            card.pop("span", None)
            changed = True

        # 2/3. Both are decisions about *what the numbers mean*, so they are
        #      only applied where the card's own series say so - never by title,
        #      which the user is free to change.
        if _all_non_negative(card) and card.get("symmetric") is None:
            card["symmetric"] = False
            changed = True
        if _is_independent_overlay(card) and card.get("stack") is None:
            card["stack"] = False
            changed = True

    return changed


def _walk_cards(views: list[Any]) -> list[Any]:
    """Every card dict in the view tree, nested grid sections included."""
    out: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") and "cards" not in node:
            out.append(node)
        elif node.get("type") and node.get("type") != "grid":
            out.append(node)
        for key in ("cards", "sections"):
            if isinstance(node.get(key), list):
                walk(node[key])

    walk(views)
    return out


def _series_entities(card: dict[str, Any]) -> list[str]:
    """The entity ids a history chart references."""
    series = card.get("series")
    if not isinstance(series, list):
        return []
    return [s["entity"] for s in series if isinstance(s, dict) and s.get("entity")]


def _all_non_negative(card: dict[str, Any]) -> bool:
    """True when no series of this card can go below zero.

    Decided from the entity key, not from the title: a battery or grid power
    entity is signed (charge < 0, export < 0) and keeps its mirrored axis, while
    a PV port's power, a voltage and an ``*_energy*`` counter never are.
    """
    entities = _series_entities(card)
    if not entities:
        return False
    for entity in entities:
        if "battery" in entity or "grid" in entity:
            return False
        if not any(mark in entity for mark in ("pv", "power", "voltage", "energy")):
            return False
    return True


def _is_independent_overlay(card: dict[str, Any]) -> bool:
    """True when this card's series are separate readings, not additive parts.

    Two or more ``*_power`` series that are each a whole measurement (PV, grid,
    load) must be overlaid: stacking them drew the load curve on top of the PV
    curve even when the load was the smaller number.  A single series has
    nothing to stack against, so it is left alone (either setting looks the
    same), and energy series are deliberately excluded because stacking daily
    contributions is exactly right for them.
    """
    entities = _series_entities(card)
    if len(entities) < 2:
        return False
    if any("energy" in entity for entity in entities):
        return False
    return all(entity.endswith("_power") for entity in entities)



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
    dev_id: str,
    pv_count: int | None = None,
    model: str = "",
    alarm_entity: str | None = None,
) -> list[dict[str, Any]]:
    """Return the full view set for the device.

    ``pv_count`` is how many PV inputs the unit actually has, so the inverter
    views only reference per-port entities that exist.  ``None`` means "not
    known yet" and is treated as two, the common case for the inverter family
    this layout targets.  ``model`` is accepted for the callers' sake but no
    longer used: revision 11 removed the heading card that printed it.

    The unit's *role* is deliberately not a parameter.  Every dashboard is
    written complete and :func:`_async_sync_role` then hides the parts the role
    denies - a ``slave`` has no System view, because the document limits
    ``system/state`` to 「主机和单机」.  Doing it in two passes is what makes the
    hidden tab restorable: the sync keeps the exact dict it removed, so a unit
    that is later re-paired into a master/slave pair gets its tab back with every
    user edit still inside it.

    ``alarm_entity`` is the registry-resolved ``entity_id`` of the alarm sensor
    (see :func:`_alarm_entity_id`); ``None`` falls back to the conventional
    serial-based spelling, which is all a brand new device can offer.
    """
    if _is_inverter(dev_id):
        return _build_inverter_views(dev_id, pv_count, model, alarm_entity)
    return _build_storage_views(dev_id, model)


# Icon shown on each view's tab.  These are the icons the vendor app's own
# dashboard uses (`VIEW_ICON_*` in the official integration), so a dashboard
# generated here and one generated there look like the same product: a chart
# for the system overview, a battery for the device's own ports, sliders for
# the settings.
_VIEW_ICONS: dict[str, str] = {
    "system": "mdi:home-analytics",
    "device": "mdi:home-battery",
    "control": "mdi:tune",
}

# The view icons an earlier release generated.  Used by
# :func:`_migrate_view_icons` so only a tab the user has not re-iconed is
# rewritten.
_LEGACY_VIEW_ICONS: dict[str, str] = {
    "system": "mdi:solar-power-variant",
    "device": "mdi:solar-panel-large",
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


def _history(
    title: dict[str, str],
    series: list[dict[str, Any]],
    *,
    unit: str,
    height: int,
    range: str = "day",
    sync_group: str | None = None,
    symmetric: bool | None = None,
    stack: bool | None = None,
    mode: str | None = None,
    show_totals: bool | None = None,
    scale: float | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
) -> dict[str, Any]:
    """A ``hoymiles-g2-history-chart`` card spanning the full section width.

    The y axis is left to the card: it rounds the *measured* maximum up to the
    next 1/2/5 × 10^n step, so a 490 W peak gets a 0..500 W axis instead of
    floating in the bottom quarter of a fixed one.  A fixed ``span`` is
    therefore wrong here and no longer emitted - it made every generated chart
    draw a 2 000 W / 2 500 W axis regardless of the data, which is what made a
    490 W curve look tiny.

    ``symmetric=False`` switches the axis to a bottom-up ``0..max`` scale.  The
    default (mirrored around zero) is right for a single reading that changes
    sign - battery charge/discharge, grid import/export - but halves the usable
    height for an always-positive one (PV power, voltage, energy), which is the
    other half of why those curves looked flat.  ``stack=False`` overlays the
    curves instead of stacking them; PV power, grid power and load power are
    three independent measurements, not additive parts of one total, so stacking
    them drew the load curve *on top of* the PV curve even while the load was
    the smaller of the two.

    ``range`` is the period the card opens on.  Every power chart wants a day -
    that is the window a curve is read in - while the energy card opens on a
    month, where one bar per day is the question being asked.
    """
    card: dict[str, Any] = {
        "type": "custom:hoymiles-g2-history-chart",
        "title": title,
        "range": range,
        "series": series,
        "unit": unit,
        "height": height,
    }
    if sync_group is not None:
        card["sync_group"] = sync_group
    if symmetric is not None:
        card["symmetric"] = symmetric
    if stack is not None:
        card["stack"] = stack
    # ``mode: auto`` lets the card pick bars for the month / year energy view
    # and a curve for a day; a power card must stay ``line`` because the sum of
    # instantaneous watts has no meaning.
    if mode is not None:
        card["mode"] = mode
    if show_totals is not None:
        card["show_totals"] = show_totals
    # Statistics are read in the sensor's own unit (Wh), but 20 910 Wh on an
    # axis is unreadable.  ``scale`` converts once, up front, so the bars, the
    # axis, the tooltip and the tiles all speak kWh.
    if scale is not None:
        card["scale"] = scale
    # A fixed axis range, for a reading that does not scale with its own data:
    # a dBm level lives between -100 and 0, so an axis derived from the measured
    # maximum would either top out at a round 0 dBm or, mirrored, waste half the
    # height on a positive half that can never be filled.
    if min_value is not None:
        card["min"] = min_value
    if max_value is not None:
        card["max"] = max_value
    return _full_width(card)


# --------------------------------------------------------------------------- #
# Optional device charts
# --------------------------------------------------------------------------- #
# The readings ``device/state`` publishes that the generated Device view does
# not draw.
#
# Deliberately short, and deliberately not everything §25 carries: the ``grid``
# array is a structure rather than a series, the PV string ids and the running
# EMS mode are not measurements, and everything under ``pack*`` belongs to a
# storage unit - which the option does not offer at all.  What is left is the
# per-reading telemetry a HiFlow / HiFlow Pro actually reports.
#
# Grid voltage is *not* in this list even though it is a per-reading
# measurement: the Device view has drawn its own "Grid Voltage" card since the
# first release, and offering it again would put two identical curves on the
# same page the moment it was ticked.
#
#   entity   sensor key (``sensor.<slug>_<entity>``)
#   unit     the axis label
#   color    curve colour
#   en / zh  title, resolved against the viewing user's UI language
#   axis     ``"level"`` for a quantity that is always positive (a bottom-up
#            axis fills the card), ``"signed"`` to let the card decide from the
#            data - which is what a reactive power reading needs, since it
#            changes sign with the power factor - or a ``(min, max)`` pair for
#            a fixed range (a dBm level lives between -100 and 0 and would sit
#            in the wrong half of an axis derived from the data alone).
OPTIONAL_CHARTS: dict[str, dict[str, Any]] = {
    "grid_current": {
        "entity": "grid_on_current",
        "unit": "A",
        "color": "#f59e0b",
        "en": "Grid Current",
        "zh": "电网电流",
        "axis": "level",
    },
    "grid_frequency": {
        "entity": "grid_on_frequency",
        "unit": "Hz",
        "color": "#8b5cf6",
        "en": "Grid Frequency",
        "zh": "电网频率",
        "axis": "level",
    },
    "active_power": {
        "entity": "grid_on_power_5m",
        "unit": "W",
        "color": "#22c55e",
        "en": "Active Power",
        "zh": "有功功率",
        # The AC port exports while the sun is up and draws a little at night,
        # so the sign is a property of the data rather than of the reading.
        "axis": "signed",
    },
    "reactive_power": {
        "entity": "grid_on_reactive_power",
        "unit": "var",
        "color": "#06b6d4",
        "en": "Reactive Power",
        "zh": "无功功率",
        "axis": "signed",
    },
    "rssi": {
        "entity": "rssi",
        "unit": "dBm",
        "color": "#94a3b8",
        "en": "Signal Strength",
        "zh": "信号强度",
        # A dBm reading is negative and bounded, so an axis derived from the
        # data would either mirror it around zero or leave the curve pinned to
        # the top edge. -100..0 puts the zero line at the bottom and every
        # reading on the same scale, which is how a signal strength is read.
        "axis": (-100, 0),
    },
}

# Marker written on every card this section adds, holding its ``OPTIONAL_CHARTS``
# key.  It is the only safe way to find them again: the cards are ordinary
# history charts, indistinguishable from a hand-added one by their ``type``, and
# a title is something the user may edit.  The chart ignores unknown keys.
_OPTIONAL_KEY = "g2_optional"

# Chart cards added at the bottom of the Device view, in this order.
_OPTIONAL_ORDER: tuple[str, ...] = tuple(OPTIONAL_CHARTS)


def _now_iso() -> str:
    """The current instant as an ISO 8601 UTC string (second precision)."""
    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _optional_card(
    key: str, dev_id: str, since: str | None, entity: str | None = None
) -> dict[str, Any]:
    """Build one opt-in history chart of the Device view.

    ``since`` is the instant the card was enabled and goes into the card's own
    config: the statistics from before it are still in the recorder, so the
    curve is clipped there rather than the sensor being recreated.

    ``entity`` is the already-resolved ``entity_id``; it is optional so a caller
    that has no ``hass`` yet (a unit test, a pure layout build) still gets a
    usable card from the conventional id.
    """
    spec = OPTIONAL_CHARTS[key]
    title = _t(spec["en"], spec["zh"])
    series = [
        {
            "entity": entity or _entity(dev_id, spec["entity"]),
            "name": title,
            "color": spec["color"],
        }
    ]
    axis = spec["axis"]
    extra: dict[str, Any] = {}
    if axis == "level":
        extra["symmetric"] = False
    elif isinstance(axis, tuple):
        extra["symmetric"] = False
        extra["min_value"] = axis[0]
        extra["max_value"] = axis[1]
    # ``signed`` is left to the card, which mirrors the axis exactly when the
    # series actually crosses zero.
    card = _history(
        title,
        series,
        unit=spec["unit"],
        height=240,
        sync_group=f"{_slug(dev_id)}-device",
        stack=False,
        **extra,
    )
    card[_OPTIONAL_KEY] = key
    if since:
        card["since"] = since
    return card


def _repoint_card(card: dict[str, Any], entity: str) -> bool:
    """Point a stored opt-in card's single series at ``entity``.

    Returns True when the card actually changed.  Only the series entity is
    rewritten - the title, colour, axis limits and above all ``since`` are the
    user's, and a card that already names the right entity is left untouched so
    re-saving a form is idempotent.
    """
    series = card.get("series")
    if not isinstance(series, list) or len(series) != 1:
        return False
    only = series[0]
    if not isinstance(only, dict):
        return False
    if only.get("entity") == entity:
        return False
    only["entity"] = entity
    return True


async def async_get_optional_charts(hass: HomeAssistant, dev_id: str) -> dict[str, str]:
    """Return ``{key: since}`` for the opt-in cards currently on the dashboard.

    ``since`` is the instant the card was enabled (``""`` when the card carries
    none, e.g. one added by hand).  Used by the options flow to preselect the
    checkboxes, and it is the *stored dashboard* that is the source of truth -
    there is no second copy of this list to fall out of step with what the user
    actually sees.
    """
    try:
        store = await _async_find_store(hass, _url_path(dev_id))
        if store is None:
            return {}
        config = await _async_read_storage(hass, store) or {}
        if not isinstance(config, dict):
            return {}
        found: dict[str, str] = {}
        for card in _walk_cards(config.get("views") or []):
            if not isinstance(card, dict):
                continue
            key = card.get(_OPTIONAL_KEY)
            if key in OPTIONAL_CHARTS:
                found[key] = str(card.get("since") or "")
        return found
    except Exception:  # noqa: BLE001 - a checkbox default is never worth raising
        _LOGGER.debug("Could not read the optional charts of %s", dev_id, exc_info=True)
        return {}


async def async_set_optional_charts(
    hass: HomeAssistant, dev_id: str, wanted: dict[str, bool]
) -> bool:
    """Add / remove the opt-in charts of the Device view; return True if saved.

    Idempotent and non-destructive:

    * every optional card is taken out first, so the wanted set is applied from
      scratch - but a card that stays enabled is re-inserted *its own dict*,
      which is what preserves the instant it was enabled (and anything the user
      changed inside it);
    * a grid section is left in place when the user put cards of their own in
      it, and dropped only once it is empty;
    * nothing else in the dashboard is touched - titles, order, extra views and
      hand-added cards all survive.

    Only a micro inverter is acted on: these are the ``grid_on_*`` readings and
    the Device view of a storage unit is a different layout.
    """
    if not _is_inverter(dev_id):
        return False

    url_path = _url_path(dev_id)
    try:
        store = await _async_find_store(hass, url_path)
        if store is None:
            return False
        config = await _async_read_storage(hass, store) or {}
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not read dashboard %s", url_path, exc_info=True)
        return False

    if not isinstance(config, dict):
        return False
    views = config.get("views")
    if not isinstance(views, list):
        return False

    # 1. Take every optional card out, remembering the ones that stay enabled so
    #    their config - above all their ``since`` - is reused verbatim.
    kept: dict[str, dict[str, Any]] = {}
    touched = False
    for view in views:
        if not isinstance(view, dict) or view.get("path") != "device":
            continue
        sections = view.get("sections")
        if not isinstance(sections, list):
            continue
        for section in list(sections):
            if not isinstance(section, dict):
                continue
            cards = section.get("cards")
            if not isinstance(cards, list):
                continue
            rest: list[Any] = []
            for card in cards:
                if isinstance(card, dict) and card.get(_OPTIONAL_KEY) in OPTIONAL_CHARTS:
                    key = card[_OPTIONAL_KEY]
                    if wanted.get(key):
                        kept.setdefault(key, card)
                    touched = True
                    continue
                rest.append(card)
            if len(rest) == len(cards):
                continue
            if rest:
                section["cards"] = rest
            else:
                sections.remove(section)

    # 2. Put the wanted ones back, at the bottom of the Device view, in the fixed
    #    order of ``OPTIONAL_CHARTS``.
    added: list[dict[str, Any]] = []
    for key in _OPTIONAL_ORDER:
        if not wanted.get(key):
            continue
        entity = _resolve_entity(hass, dev_id, OPTIONAL_CHARTS[key]["entity"])
        card = kept.get(key)
        if card is None:
            card = _optional_card(key, dev_id, _now_iso(), entity)
            touched = True
        else:
            # A kept card is reused as-is so its ``since`` survives, but its
            # series is re-pointed at the real entity: an older release wrote
            # the conventional id, which is wrong for any reading whose display
            # name is not its key (``grid_on_power_5m`` is stored at
            # ``grid_on_power_5_min``), and a card pointing at a non-existent
            # entity draws nothing at all.  Re-saving the same ticks therefore
            # repairs such a card instead of preserving the mistake.
            touched = _repoint_card(card, entity) or touched
        added.append(card)

    if added:
        for view in views:
            if isinstance(view, dict) and view.get("path") == "device":
                sections = view.setdefault("sections", [])
                if isinstance(sections, list):
                    # Directly above the switch card, so the curves read as a
                    # block under the fixed ones and the switch that owns them
                    # stays at the bottom of the page.  A dashboard without that
                    # card (an older layout) simply gets them appended.
                    at = len(sections)
                    for index, section in enumerate(sections):
                        if _is_chart_options_section(section):
                            at = index
                            break
                    sections.insert(at, _grid(added))
                    touched = True
                break

    if not touched:
        # The stored dashboard already matches the wanted set - ticking the
        # same boxes again is a no-op, not a failure, so it must not surface as
        # "could not write the dashboard" to the user.
        return True

    try:
        await store.async_save({**config, "views": views})
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not save dashboard %s", url_path, exc_info=True)
        return False

    _LOGGER.info(
        "Dashboard %s: optional charts now %s",
        url_path,
        ", ".join(sorted(k for k in _OPTIONAL_ORDER if wanted.get(k))) or "none",
    )
    return True


# --------------------------------------------------------------------------- #
# Micro inverter (RMI-) views
# --------------------------------------------------------------------------- #
def _build_inverter_views(
    dev_id: str,
    pv_count: int | None = None,
    model: str = "",
    alarm_entity: str | None = None,
) -> list[dict[str, Any]]:
    """System / device / control views for a grid-tied micro inverter.

    Mirrors the hand-built reference dashboard: one full-width power flow and
    history charts that share a ``sync_group`` so every curve on a page moves
    with the same time window.

    Every per-port reference is generated from ``pv_count`` so a single-input
    unit does not get gauges and history series pointing at sensors that this
    integration never created for it.
    """
    ports = pv_count if pv_count and pv_count >= 1 else 2
    slug = _slug(dev_id)
    system_group = f"{slug}-system"
    device_group = f"{slug}-device"
    # The energy bars are a different kind of axis (kWh, one bar per day) from
    # the power curves, so they keep their own window instead of dragging the
    # power chart onto the same statistic grid.
    system_energy_group = f"{slug}-energy"

    pv_series = {
        "entity": _entity(dev_id, "system_pv_power"),
        "name": _t("PV Power", "光伏功率"),
        "color": "#22c55e",
    }
    grid_series = {
        "entity": _entity(dev_id, "system_grid_power"),
        "name": _t("Grid Output [+]/Input [-]", "电网 输出[+]/输入[-]"),
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
        "title": _t("My Home", "我的家"),
        "max_width": 700,
        "show_title": False,
    }

    system = _view(
        "system",
        "System",
        [
            _grid(
                [
                    _subgrid(
                        [
                            _full_width(power_flow),
                            _subgrid(
                                [
                                    _gauge(
                                        dev_id,
                                        "system_pv_energy_today",
                                        _t("PV Today", "今日发电"),
                                        "Wh",
                                        max=2000,
                                        decimals=0,
                                        icon="panel",
                                        show_arc=False,
                                    ),
                                    _energy_total_gauge(dev_id),
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
                        symmetric=False,
                        stack=False,
                    )
                ]
            ),
            _grid(
                [
                    # Energy, not power: one bar per day of a month and one per
                    # month of a year, a smooth curve for a single day.  The
                    # three tiles above it (month / year / lifetime) are derived
                    # from the same lifetime statistic, so no extra sensor is
                    # needed for "this month" and "this year".
                    _history(
                        _t("PV Energy", "发电量"),
                        [
                            {
                                "entity": _entity(dev_id, "pv_energy_total"),
                                "name": _t("Generation", "发电量"),
                                "color": "#22c55e",
                            }
                        ],
                        unit="kWh",
                        height=300,
                        # Opens on a month: one bar per day of it, which is the
                        # window the vendor app shows and the only one where
                        # "how much did it make" is a single row of bars.
                        range="month",
                        sync_group=system_energy_group,
                        symmetric=False,
                        stack=False,
                        mode="auto",
                        show_totals=True,
                        scale=0.001,
                    )
                ]
            ),
        ],
    )

    device = _view(
        "device",
        "Device",
        [
            # One row, filled edge to edge: half the section's 48 columns of
            # schematic and half of faults.  Both cards are siblings in a single
            # grid section - a nested ``grid`` card would also give equal halves
            # but cannot be collapsed later, and two sibling sections would
            # stack once the dashboard drops ``max_columns``.  The alarm card
            # hides itself while the device is quiet, and the schematic then
            # widens over the freed columns by itself (``_syncRowSpan``).
            _grid(
                [
                    {
                        **power_flow,
                        "variant": "inverter",
                        "pv_count": ports,
                        "max_width": _DEVICE_FLOW_MAX_WIDTH,
                        "grid_options": {"columns": _FLOW_COLUMNS},
                        # The alarm list beside this card hides itself when the
                        # device is quiet, so the badge in the schematic corner
                        # is the only remaining indication of health.  It needs
                        # the sensor to count with; without it the badge is
                        # simply omitted.
                        **({"alarm_entity": alarm_entity} if alarm_entity else {}),
                    },
                    {**_alarm_card(dev_id, alarm_entity), "grid_options": {"columns": _ALARM_COLUMNS}},
                ]
            ),
            _grid(
                [
                    _history(
                        _t("PV Power by Port", "各光伏端口功率"),
                        port_series,
                        unit="W",
                        height=280,
                        sync_group=device_group,
                        symmetric=False,
                        stack=False,
                    )
                ]
            ),
            # The 功率曲线 card that used to sit here is gone.  The System view
            # already draws PV / grid / load together, and on this tab the three
            # curves answered a question nobody asks of *one* unit: the port
            # chart above already says which input is producing, and the two
            # cards below cover voltage and yield.  Keeping it also meant the
            # same three series were stored twice per device.
            _grid(
                [
                    _history(
                        _t("Grid Voltage", "电网电压"),
                        [
                            {
                                "entity": _entity(dev_id, "grid_on_voltage"),
                                "name": _t("Grid Voltage", "电网电压"),
                                "color": "#60a5fa",
                            }
                        ],
                        unit="V",
                        height=240,
                        sync_group=device_group,
                        symmetric=False,
                    ),
                    _history(
                        _t("Energy Today", "今日发电量"),
                        [
                            {
                                "entity": _entity(dev_id, "system_pv_energy_today"),
                                "name": _t("PV Today", "今日发电"),
                                "color": "#fbbf24",
                            }
                        ],
                        unit="Wh",
                        height=240,
                        sync_group=device_group,
                        symmetric=False,
                    ),
                ]
            ),
            # The switch for the opt-in curves.  Last, so the curves it adds read
            # as a block right above it (``async_set_optional_charts`` appends
            # them, i.e. just before this section).
            _grid([_chart_options_card(dev_id)]),
        ],
    )

    control = _view(
        "control",
        "Control",
        [
            _grid(
                [
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-control",
                            "dev_id": dev_id,
                            "subtitle": False,
                            # A micro inverter has no time-of-use feature: its
                            # retained `attributes` inventory carries no
                            # `tou_get` (verified live - alarm_state,
                            # device_state, ems_mode, factory_reset,
                            # output_power, power_ctrl, quick_state, reboot,
                            # reset_ble_pin_code, switch_ctrl), and the firmware
                            # never publishes a `tou_*` topic. The row is
                            # switched off explicitly instead of relying on the
                            # entity being absent, so a registry row left over
                            # from an older build cannot bring the button back.
                            "show_tou": False,
                            # No ``entities`` pin here, deliberately. Both
                            # `power_ctrl` and `output_power` are plain `number`
                            # entities and the firmware names them all after the
                            # device, so `number.<dev>` is whichever one HA
                            # created first - measured, `output_power` on the
                            # two-input HiFlow Pro but `power_ctrl` on the
                            # single-input HiFlow. Pinning the base id therefore
                            # only moved the bug between models: the Control
                            # card of a HiFlow offered `100 ~ 800` on its
                            # power-control row and `0 ~ 132` on its output row,
                            # i.e. each row showed the other's range. The card
                            # tells the two apart from the declared floor
                            # (`power_ctrl` can reach 0 or below, `output_power`
                            # starts at 100 W), which holds on every model.
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

    Same frame as the inverter layout - full-width power flow, icon and title on
    every view, shared ``sync_group`` on the history charts.
    """
    slug = _slug(dev_id)
    group = f"{slug}-system"
    system = _view(
        "system",
        "System",
        [
            _grid(
                [
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-power-flow",
                            "dev_id": dev_id,
                            "title": _t("My Home", "我的家"),
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
                        _t("PV Today", "今日发电"),
                        "kWh",
                        scale=0.001,
                        icon="panel",
                    ),
                    _gauge(
                        dev_id,
                        "battery_charge_energy_today",
                        _t("Charge Today", "今日充电"),
                        "kWh",
                        scale=0.001,
                        icon="battery",
                    ),
                    _gauge(
                        dev_id,
                        "battery_discharge_energy_today",
                        _t("Discharge Today", "今日放电"),
                        "kWh",
                        scale=0.001,
                        icon="cycle",
                    ),
                    _gauge(
                        dev_id,
                        "system_soc",
                        _t("Battery SOC", "电池电量"),
                        "%",
                        max=100,
                        min=0,
                        icon="battery",
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
                                "name": _t("PV Power", "光伏功率"),
                                "color": "#22c55e",
                            },
                            {
                                "entity": _entity(dev_id, "system_battery_power"),
                                "name": _t("Battery", "电池"),
                                "color": "#4a90d9",
                            },
                            {
                                "entity": _entity(dev_id, "system_grid_power"),
                                "name": _t("Grid Output [+]/Input [-]", "电网 输出[+]/输入[-]"),
                                "color": "#22d3ee",
                            },
                        ],
                        unit="W",
                        height=330,
                        sync_group=group,
                        stack=False,
                    )
                ]
            ),
            _grid(
                [
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-energy-sankey",
                            "dev_id": dev_id,
                            "title": _t("Energy Flow", "能量流"),
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
                            "title": _t("Battery Packs", "电池组"),
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
                    _full_width(
                        {
                            "type": "custom:hoymiles-g2-control",
                            "dev_id": dev_id,
                            "subtitle": False,
                            # Protocol §29 declares the factory-reset command for
                            # HiFlow / HiFlow Pro only, and a storage unit's
                            # retained `attributes` inventory carries no
                            # `factory_reset` entry. The card reaches the same
                            # conclusion from the product id on its own; this is
                            # written out so the intent survives a look at the
                            # generated dashboard.
                            "show_factory_reset": False,
                            # Same reasoning for protocol §31 (BLE PIN reset) -
                            # a storage unit declares `reset_ble_pin_code` neither.
                            "show_ble_pin_reset": False,
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
                            "title": _t("TOU Plan", "峰谷计划"),
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


def _energy_total_gauge(dev_id: str) -> dict[str, Any]:
    """The lifetime PV energy card that sits to the right of "today".

    Same card and the same visual format as the "today" gauge next to it - a
    number with a unit and no arc - because the two are read together.  Three
    things do differ, all deliberately:

    * **kWh, not Wh.**  ``pv_energy_total`` is a lifetime counter; the
      micro inverter measured here reports 1 593 161 Wh, which is seven digits
      and overflows a half-width card on a phone.  Scaled to kWh it reads
      ``1 593.2``.
    * **A different icon.**  "Today" uses ☀️; repeating the sun on the adjacent
      card makes the two indistinguishable at a glance.  This one uses the
      vendor app's "All" ring - a broken circle with the word inside - which
      says "everything generated so far" without inventing a second sun.  The
      glyph is drawn by the card itself (``ICON_SVG.all``); set the option to
      ``all`` and it lands in the head at the same size as any emoji.
    * **One decimal.**  A tenth of a kWh is the smallest step that ever matters
      on a lifetime total, and it keeps the width stable as the number grows.

    ``show_arc`` stays off for the same reason as its sibling: a lifetime total
    has no meaningful ceiling, so a percentage of ``max`` would be invented.
    """
    return _gauge(
        dev_id,
        "pv_energy_total",
        _t("PV Total", "总发电量"),
        "kWh",
        scale=0.001,
        decimals=1,
        icon="all",
        show_arc=False,
    )


def _chart_options_card(dev_id: str) -> dict[str, Any]:
    """The 「更多数据」 switch card of the Device view.

    It is the on-page counterpart of the Options Flow's data-card step: five
    switches, one per :data:`OPTIONAL_CHARTS` entry, writing the same dashboard
    document through the integration's ``set_optional_charts`` service.  The
    card carries ``dev_id`` because it has no entity to infer the device from -
    it acts on the dashboard the reader is already looking at.

    The title is 「更多数据」 and not 「更多曲线」: it switches *readings*, and the
    cards it adds are charts the user chose from the data the device reports.

    It is deliberately *not* marked with :data:`_OPTIONAL_KEY`: that marker means
    "this card is one of the opt-in charts" and
    :func:`async_set_optional_charts` removes every card carrying it.  Marking
    this one would make it delete itself the first time a switch was used.
    """
    return {
        "type": CHART_OPTIONS_CARD,
        "dev_id": dev_id,
        "title": _t("More Data", "更多数据"),
    }


def _is_chart_options_section(section: Any) -> bool:
    """True when this grid section holds the opt-in switch card."""
    if not isinstance(section, dict):
        return False
    cards = section.get("cards")
    if not isinstance(cards, list):
        return False
    return any(
        isinstance(card, dict) and card.get("type") == CHART_OPTIONS_CARD
        for card in cards
    )


def _has_chart_options(config: dict[str, Any]) -> bool:
    """True when the dashboard already carries the switch card somewhere."""
    views = config.get("views")
    if not isinstance(views, list):
        return False
    for card in _walk_cards(views):
        if isinstance(card, dict) and card.get("type") == CHART_OPTIONS_CARD:
            return True
    return False


def _migrate_chart_options_card(config: dict[str, Any], dev_id: str) -> bool:
    """Add the 「更多曲线」 switch card to an inverter's Device view; rev. 21.

    ``_LAYOUT_KEY`` short-circuits :func:`_build_views`, so an install that
    already has a dashboard never sees a newly generated card without this.

    It only ever *adds*, and only to the Device view of a micro inverter - the
    storage unit's layout has no opt-in charts, and its Device view is left
    byte-for-byte alone.  The card goes last, after the fixed curves, so the
    opt-in ones (which :func:`async_set_optional_charts` inserts just above it)
    read as a block under the readings they extend.
    """
    if not _is_inverter(dev_id):
        return False

    if _has_chart_options(config):
        return False

    views = config.get("views")
    if not isinstance(views, list):
        return False

    for view in views:
        if not isinstance(view, dict) or view.get("path") != "device":
            continue
        sections = view.setdefault("sections", [])
        if not isinstance(sections, list):
            return False
        sections.append(_grid([_chart_options_card(dev_id)]))
        return True

    return False


def _migrate_chart_options_title(config: dict[str, Any]) -> bool:
    """Rename the switch card's stored title to 「更多数据」; rev. 22.

    The title lives in the dashboard document, so a new default in
    :func:`_chart_options_card` only reaches *new* dashboards - every install
    that already has the card would keep reading 「更多曲线」 forever.

    Only the title an earlier release wrote is rewritten.  A title the user typed
    (anything else) is theirs and is left alone, because the card renders
    ``config.title`` and a user-chosen label must not be overwritten by a rename
    of ours.
    """
    changed = False
    for card in _walk_cards(config.get("views") or []):
        if not isinstance(card, dict) or card.get("type") != CHART_OPTIONS_CARD:
            continue
        if card.get("title") not in _LEGACY_CHART_OPTIONS_TITLES:
            continue
        card["title"] = _t("More Data", "更多数据")
        changed = True
    return changed


def _alarm_card(dev_id: str, entity: str | None = None) -> dict[str, Any]:
    """The device-alarm card that sits to the right of the power flow.

    It reads the ``Active Alarms`` sensor, whose state is the count and whose
    ``alarms`` attribute is the decoded list (protocol §27).  The card itself
    decides between "no data", "no alarms" and the list - it has to, because
    ``alarm/state`` is not retained and a silent device must not be shown as a
    healthy one.

    ``entity`` is the id resolved from the registry by
    :func:`_alarm_entity_id`.  It is passed in rather than recomputed so the
    generated card and the migration agree, and so a rename that moved the
    ``entity_id`` away from the serial-based spelling still resolves.
    ``max`` is capped at six rows: the card shares a row with the power flow, so
    a long list scrolls inside it instead of stretching the row.
    """
    return {
        "type": ALARM_CARD,
        "entity": entity or _entity(dev_id, "active_alarms"),
        "title": _t("Alarms", "设备告警"),
        "max": 6,
        # The card hides itself while the device reports nothing, which lets the
        # schematic beside it take the whole row.  The schematic carries a small
        # badge instead (green tick / red lamp), so the state is never lost - and
        # a device that has *never* reported is shown as unknown on the badge
        # rather than as healthy.
        "only_when_alarm": True,
    }


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
