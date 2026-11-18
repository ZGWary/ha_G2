"""The Hoymiles Micro Storage integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_DEV_ID,
    DOMAIN,
    FRONTEND_ASSETS,
    FRONTEND_IMAGES,
    FRONTEND_URL,
    PLATFORMS,
)
from .coordinator import HoymilesCoordinator
from .discovery_override import FirmwareDiscoveryPatcher
from .keepalive import PowerCtrlKeepAlive
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hoymiles Micro Storage from a config entry."""
    dev_id: str = entry.data[CONF_DEV_ID]

    coordinator = HoymilesCoordinator(hass, dev_id)
    await coordinator.async_setup()

    # Patch the firmware's retained discovery payloads so the entities it
    # registers itself comply with Home Assistant's per-domain schemas.  See
    # discovery_override.py for the list of patches; it is a no-op once the
    # firmware ships compliant payloads.
    # Some capabilities have no ``supported_topics`` entry - the multi phase
    # output limit only exists as its own discovery object - so the patcher
    # reports what it sees and the coordinator merges it into the same set.  The
    # callback is installed before the subscription starts, otherwise a retained
    # config could arrive before anybody listens.
    patcher = FirmwareDiscoveryPatcher(hass, dev_id)
    patcher.on_object = lambda name, present: (
        coordinator.add_capability(name) if present else None
    )
    await patcher.async_setup()

    # Once per connection, delete the retained discovery configs this connection
    # never published.  A retained config outlives the connection that published
    # it and the broker replays it to every new subscriber, so without this a
    # feature the firmware dropped keeps its entities forever - and the entities
    # of a retired node id (``MI-<SN>``) come back on every restart.
    #
    # The rule is what the device itself publishes, not the ``supported_topics``
    # list: that list is incomplete (this unit declares four keys while publishing
    # far more), so treating it as the keep-set deleted working entities and kept
    # dead ones.  The patcher therefore compares against the discovery topics the
    # device published live on this connection, and does nothing when it published
    # none (i.e. it is offline and everything seen was a replay).
    def _maybe_prune() -> None:
        patcher.async_schedule_prune(lambda: coordinator.session)

    entry.async_on_unload(coordinator.async_add_listener(_maybe_prune))
    _maybe_prune()

    # Re-publishes `power_ctrl` so the firmware's ~60 s lease stays in force.
    # It lives here rather than in the card, because a browser timer stops the
    # moment the dashboard is closed - exactly when the lease still needs
    # holding.  Not started on its own: only a service call / the card arms it.
    # Its state is pushed through the coordinator so the keep-alive sensor can
    # mirror it, which is how the card knows the truth after a page reload.
    keepalive = PowerCtrlKeepAlive(
        hass,
        dev_id,
        coordinator,
        on_change=coordinator.set_keepalive_state,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "patcher": patcher,
        "dev_id": dev_id,
        "keepalive": keepalive,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Seed the idle state now that the entities exist, so the card can tell
    # "never started" from "running" on the very first render.
    await keepalive.async_publish_initial_state()

    await _async_register_frontend(hass)
    await async_setup_services(hass)

    # Best-effort: materialise the device's Lovelace dashboard on first setup,
    # mirroring the official integration's auto-generated panel.  Never raises.
    # ``pv_count`` is resolved from the product code even before the first
    # ``device/state`` arrives, so a fresh install picks the right layout.
    from . import lovelace  # noqa: PLC0415

    await lovelace.async_ensure_dashboard(
        hass, dev_id, coordinator.pv_count, coordinator.role
    )
    # The role rides on ``event/state``, which the device publishes on its own
    # schedule - frequently *after* this point.  The dashboard is written now
    # because waiting for it would delay setup by an unbounded amount of time,
    # so a late arrival is applied as it lands: each change costs one storage
    # read and one write, and ``None`` (never heard from) leaves it alone.
    _async_track_role(hass, entry, coordinator, dev_id, lovelace)

    return True


@callback
def _async_track_role(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: HoymilesCoordinator,
    dev_id: str,
    lovelace: Any,
) -> None:
    """Re-apply the dashboard's role gate whenever ``event/state`` changes it.

    Registered as a coordinator listener rather than an MQTT subscription: every
    payload the firmware sends already fans out through the coordinator, so this
    adds no traffic.  The listener is removed with the config entry, and the last
    applied role is remembered in ``lovelace`` - so this is normally a no-op.

    The whole body is guarded: a Lovelace internals change must never be able to
    raise inside a coordinator callback, which would be logged against the
    integration on every single MQTT message.
    """
    last: list[Any] = [coordinator.role]

    @callback
    def _apply() -> None:
        try:
            role = coordinator.role
            if role == last[0]:
                return
            last[0] = role
            hass.async_create_task(lovelace.async_sync_role(hass, dev_id, role))
        except Exception:  # noqa: BLE001 - never break the state update
            _LOGGER.debug("Role listener failed for %s", dev_id, exc_info=True)

    entry.async_on_unload(coordinator.async_add_listener(_apply))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry_data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if entry_data:
            keepalive = entry_data.get("keepalive")
            if keepalive is not None:
                # Stop before the coordinator goes away: the final state
                # publish still needs the MQTT connection to be alive.
                await keepalive.async_shutdown()
            entry_data["patcher"].async_shutdown()
            await entry_data["coordinator"].async_shutdown()
    return unloaded


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace cards and inject them as frontend modules.

    Every asset listed in ``const.FRONTEND_ASSETS`` is published under
    ``FRONTEND_URL`` and appended with ``add_extra_js_url``, so users never
    have to register the cards manually as Lovelace resources.

    The assets are served with ``Cache-Control: no-cache``: the browser may keep
    them, but it has to revalidate before every use.  Home Assistant's own static
    path helper is not usable here - it either promises a one month cache or
    sends no cache directive at all (``web.FileResponse`` only carries
    ``ETag``/``Last-Modified``), and with no directive a browser is free to reuse
    its copy without asking.  That is what made an updated card keep running the
    old code until the user cleared the cache by hand or restarted Home
    Assistant.  Revalidating costs a 304 when the file is unchanged, and the new
    body as soon as it is.  The ``?v=`` query string is kept as well: it is a
    second line of defence and makes the URL self-documenting.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_frontend_registered"):
        return

    # Reading ``www/`` (existence checks and mtimes) is blocking IO, so it runs
    # in an executor thread instead of on the event loop.
    www_dir = Path(__file__).parent / "www"
    assets: list[tuple[str, str, int]] = await hass.async_add_executor_job(
        _collect_assets, www_dir
    )

    if not assets:
        _LOGGER.warning("No frontend assets found in %s, skipping frontend setup", www_dir)
        return

    http = getattr(hass, "http", None)
    if http is None:
        _LOGGER.debug("No HTTP component available, skipping static path registration")
        return

    if not _register_asset_routes(http, assets):
        # No aiohttp application to attach to (very old or unusual setup); fall
        # back to the helper, which at least serves the files.
        try:
            from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

            await http.async_register_static_paths(
                [StaticPathConfig(url, path, cache_headers=False) for url, path, _v in assets]
            )
        except ImportError:
            # Home Assistant < 2024.7
            for url, path, _v in assets:
                http.register_static_path(url, path, False)
        except Exception:  # noqa: BLE001 - never break setup because of the cards
            _LOGGER.warning("Unable to serve the Hoymiles frontend cards", exc_info=True)
            return

    try:
        from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415

        # The version is only used to bust the browser cache: the route matches
        # on the path and ignores the query string. Images are served by the
        # same routes but must never be injected as modules.
        for url, _path, version in assets:
            if Path(url).suffix.lower() not in {".js"}:
                continue
            add_extra_js_url(hass, f"{url}?v={version}")
    except Exception:  # noqa: BLE001 - never break setup because of the card
        _LOGGER.warning("Unable to register the Hoymiles frontend cards", exc_info=True)
        return

    domain_data["_frontend_registered"] = True
    _LOGGER.debug("Registered frontend assets: %s", [url for url, _p, _v in assets])


def _register_asset_routes(http: Any, assets: list[tuple[str, str, int]]) -> bool:
    """Serve each asset with a revalidating cache directive.

    Returns False when there is no aiohttp router to register on, so the caller
    can fall back to Home Assistant's static path helper.
    """
    app = getattr(http, "app", None)
    router = getattr(app, "router", None)
    if router is None:
        return False

    try:
        from aiohttp import web  # noqa: PLC0415
        from aiohttp.hdrs import CACHE_CONTROL  # noqa: PLC0415
    except ImportError:  # pragma: no cover - aiohttp is always there in practice
        return False

    for url, path, _version in assets:

        async def _serve(_request, _path=path):
            return web.FileResponse(_path, headers={CACHE_CONTROL: "no-cache"})

        router.add_get(url, _serve)
    return True


def _collect_assets(www_dir: Path) -> list[tuple[str, str, int]]:
    """Return ``(url, path, version)`` for every bundled asset that exists.

    Touches the file system, so it must be called through
    ``hass.async_add_executor_job`` rather than from the event loop.

    ``FRONTEND_IMAGES`` are served too, but the caller must not inject them as
    JavaScript modules.
    """
    assets: list[tuple[str, str, int]] = []
    for filename in (*FRONTEND_ASSETS, *FRONTEND_IMAGES):
        asset_path = www_dir / filename
        if not asset_path.is_file():
            _LOGGER.warning("Bundled frontend asset %s is missing, skipping", asset_path)
            continue
        assets.append(
            (f"{FRONTEND_URL}/{filename}", str(asset_path), _asset_version(asset_path))
        )
    return assets


def _asset_version(path: Path) -> int:
    """Return a cache-busting token for one bundled asset."""
    try:
        return int(path.stat().st_mtime)
    except OSError:  # pragma: no cover - unreadable file, not worth failing over
        return 0
