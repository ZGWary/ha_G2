"""The Hoymiles Micro Storage integration."""

from __future__ import annotations

import inspect
import logging
import re
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    BOOT_FILENAME,
    CONF_DEV_ID,
    DOMAIN,
    FRONTEND_ASSETS,
    FRONTEND_URL,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_URL_PATH,
    PLATFORMS,
)
from .coordinator import HoymilesCoordinator
from .discovery_override import FirmwareDiscoveryPatcher
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
    patcher = FirmwareDiscoveryPatcher(hass, dev_id)
    await patcher.async_setup()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "patcher": patcher,
        "dev_id": dev_id,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _async_register_frontend(hass)
    await _async_register_panel(hass, dev_id)
    await async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry_data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if entry_data:
            entry_data["patcher"].async_shutdown()
            await entry_data["coordinator"].async_shutdown()
        await _async_remove_panel(hass, entry.data[CONF_DEV_ID], entry.entry_id)
    return unloaded


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled frontend assets and inject the entry module.

    Every asset listed in ``const.FRONTEND_ASSETS`` is published under
    ``FRONTEND_URL``, so users never have to register anything manually as a
    Lovelace resource.  Only ``BOOT_FILENAME`` is appended with
    ``add_extra_js_url``: it imports the rest, which pins the evaluation order
    (``add_extra_js_url`` keeps its URLs in a set, so injecting all of them
    would load a card before the bootstrap that provides LitElement).

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

        # Only the boot module is injected: it imports the panel and every card
        # with static ``import`` statements.  Injecting each file separately
        # would not preserve order - ``add_extra_js_url`` keeps the URLs in a
        # set, so the ``<script>`` tags come out in an arbitrary order and a
        # card could evaluate before ``hoymiles-base.js`` provided LitElement.
        # The version is only used to bust the browser cache: the route matches
        # on the path and ignores the query string.
        boot = next((asset for asset in assets if asset[0].endswith(f"/{BOOT_FILENAME}")), None)
        if boot is None:
            _LOGGER.warning("Bundled frontend module %s is missing, cards stay disabled", BOOT_FILENAME)
            return
        boot_url = f"{boot[0]}?v={boot[2]}"
        add_extra_js_url(hass, boot_url)
        # The panel is registered with the same URL, so the browser reuses the
        # already-evaluated module instead of fetching a second copy.
        domain_data["_boot_url"] = boot_url
    except Exception:  # noqa: BLE001 - never break setup because of the card
        _LOGGER.warning("Unable to register the Hoymiles frontend cards", exc_info=True)
        return

    domain_data["_frontend_registered"] = True
    _LOGGER.debug("Registered frontend assets: %s", [url for url, _p, _v in assets])


def _panel_url_path(dev_id: str) -> str:
    """Return the sidebar URL path for one device."""
    slug = re.sub(r"[^a-z0-9]+", "-", dev_id.lower()).strip("-")
    return f"{PANEL_URL_PATH}-{slug or 'device'}"


async def _async_register_panel(hass: HomeAssistant, dev_id: str) -> None:
    """Expose ``hoymiles-panel`` as a sidebar entry for this device.

    The panel is a ``panel_custom`` page: Home Assistant loads the boot module
    as an ES module and renders ``<hoymiles-panel>`` with ``panel.config``
    available as a property, which is where ``dev_id`` comes from.  Registration
    is skipped when the assets were not served, so the sidebar never links to a
    panel that cannot render.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    url_path = _panel_url_path(dev_id)
    panels: dict[str, str] = domain_data.setdefault("_panels", {})

    if url_path in panels:
        return

    if not domain_data.get("_frontend_registered"):
        # The module was never served, so the panel could not render.
        _LOGGER.debug("Frontend assets are unavailable, skipping the sidebar panel")
        return

    try:
        from homeassistant.components.panel_custom import (  # noqa: PLC0415
            async_register_panel,
        )
    except ImportError:  # pragma: no cover - panel_custom ships with HA
        _LOGGER.debug("panel_custom is unavailable, skipping the sidebar panel")
        return

    # ``async_register_panel`` gained and dropped keyword arguments over the
    # years (``config_panel_domain`` is recent, ``trust_external`` was renamed
    # from ``trust_external_script`` in the YAML schema), so only the arguments
    # this Home Assistant actually accepts are passed.  ``js_url`` is
    # deliberately left out: giving both would make the frontend load the same
    # module twice.
    kwargs: dict[str, Any] = {
        "frontend_url_path": url_path,
        "webcomponent_name": PANEL_ELEMENT,
        "sidebar_title": dev_id,
        "sidebar_icon": PANEL_ICON,
        "module_url": domain_data.get("_boot_url") or f"{FRONTEND_URL}/{BOOT_FILENAME}",
        "embed_iframe": False,
        "trust_external": False,
        "config": {"dev_id": dev_id},
        "require_admin": False,
    }
    try:
        parameters = inspect.signature(async_register_panel).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        parameters = {}
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        kwargs = {key: value for key, value in kwargs.items() if key in parameters}

    try:
        await async_register_panel(hass, **kwargs)
    except ValueError:
        # Already registered (for example after a reload that did not unload
        # cleanly), which is the state we want anyway.
        panels[url_path] = dev_id
        return
    except Exception:  # noqa: BLE001 - a panel must never break setup
        _LOGGER.warning("Unable to register the Hoymiles sidebar panel", exc_info=True)
        return

    panels[url_path] = dev_id
    _LOGGER.debug("Registered sidebar panel %s for %s", url_path, dev_id)


async def _async_remove_panel(
    hass: HomeAssistant, dev_id: str, entry_id: str | None = None
) -> None:
    """Remove this device's sidebar panel once no entry uses it any more."""
    domain_data = hass.data.get(DOMAIN, {})
    panels: dict[str, str] = domain_data.get("_panels", {})
    url_path = _panel_url_path(dev_id)

    if panels.get(url_path) != dev_id:
        # Never registered under this path (setup failed, or it was already
        # removed by an earlier unload).
        return

    # Keep the panel while another config entry for the same device is still
    # loaded - ``async_unload_entry`` pops its own data before calling this, so
    # anything still holding this dev_id is a different, live entry.
    for other_id, other in domain_data.items():
        if other_id == entry_id or not isinstance(other, dict):
            continue
        if other.get("dev_id") == dev_id:
            return

    panels.pop(url_path, None)

    try:
        from homeassistant.components.frontend import async_remove_panel  # noqa: PLC0415

        async_remove_panel(hass, url_path)
    except Exception:  # noqa: BLE001 - a stale panel is harmless
        _LOGGER.debug("Unable to remove sidebar panel %s", url_path, exc_info=True)


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
    """
    assets: list[tuple[str, str, int]] = []
    for filename in FRONTEND_ASSETS:
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
