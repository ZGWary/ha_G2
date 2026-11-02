/* ============================================================================
 * Hoymiles Micro Storage — shared frontend bootstrap
 * ----------------------------------------------------------------------------
 * Loaded before every other card file (see ``const.FRONTEND_ASSETS``).
 *
 * Why this file exists
 * --------------------
 * Every card borrows Lit from Home Assistant instead of bundling it:
 *
 *     const LitElement = Object.getPrototypeOf(
 *       customElements.get("ha-panel-lovelace"));
 *
 * That works on a Lovelace dashboard, because the dashboard panel is what
 * defines ``ha-panel-lovelace``.  It does **not** work on any other page: the
 * sidebar panel this integration registers is a ``panel_custom`` page, and
 * ``ha-panel-lovelace`` is never defined there, so every card waited forever
 * and the panel stayed empty on a hard refresh.
 *
 * Lit is not exclusive to the Lovelace panel though — it sits in the prototype
 * chain of any Lit-based Home Assistant element, and ``ha-card`` is defined on
 * every page that can show one.  So instead of hard-coding one element, walk a
 * list of candidates and take the first prototype in the chain that exposes
 * ``html`` / ``css`` / ``requestUpdate``.
 *
 * Consumers use two globals:
 *
 *   window.__hmLit()      -> the LitElement class, or null while unavailable
 *   window.__hmWhenLit(cb) -> cb(LitElement) as soon as it is available
 *
 * Both are optional: every card falls back to its original
 * ``ha-panel-lovelace`` check, so a stale cached copy of a card keeps working
 * with a newer copy of this file (and vice versa).
 * ========================================================================== */

(function () {
  "use strict";

  if (typeof window === "undefined") return;

  /* Ordered by likelihood.  ``ha-panel-lovelace`` first keeps the dashboard
   * path byte-for-byte identical to what the cards used to do; ``ha-card`` is
   * the one that covers the custom panel.  The tail is only a safety net for
   * pages that define neither (an admin-only panel, a dialog route, ...). */
  const CANDIDATES = [
    "ha-panel-lovelace",
    "ha-card",
    "hui-masonry-view",
    "ha-form",
    "ha-dialog",
    "ha-selector",
    "ha-more-info-dialog",
  ];

  /* How deep to walk up a prototype chain.  ``ha-card`` -> LitElement is one
   * hop; the deeper entries cover intermediate base classes Home Assistant may
   * add in the future. */
  const MAX_DEPTH = 8;

  /** Return the first prototype in ``el``'s chain that is a LitElement. */
  function litFrom(el) {
    let proto = Object.getPrototypeOf(el);
    for (let depth = 0; depth < MAX_DEPTH && proto; depth += 1) {
      const p = proto.prototype;
      if (
        p &&
        typeof p.html === "function" &&
        typeof p.css === "function" &&
        typeof p.requestUpdate === "function"
      ) {
        return proto;
      }
      if (proto === HTMLElement || proto === Object.prototype) break;
      proto = Object.getPrototypeOf(proto);
    }
    return null;
  }

  /** Resolve LitElement now, or return null when nothing is defined yet. */
  function resolve() {
    for (const name of CANDIDATES) {
      const el = customElements.get(name);
      if (!el) continue;
      const lit = litFrom(el);
      if (lit) return lit;
    }
    return null;
  }

  let cached = null;

  window.__hmLit = function __hmLit() {
    if (cached) return cached;
    cached = resolve();
    return cached;
  };

  /* Callbacks waiting for Lit.  A poll is used as well as
   * ``customElements.whenDefined`` because the candidate list is probed by
   * prototype, not by a single name: an element can be defined while still not
   * being Lit (``ha-panel-custom`` is a plain class). */
  const waiting = [];
  let timer = 0;
  let attempts = 0;
  const MAX_ATTEMPTS = 1200; // ~60 s at 50 ms; a page that never defines one is broken anyway

  function flush() {
    if (!waiting.length) return;
    const lit = window.__hmLit();
    if (lit) {
      const pending = waiting.splice(0, waiting.length);
      for (const cb of pending) {
        try {
          cb(lit);
        } catch (err) {
          console.error("[hoymiles] frontend bootstrap failed", err);
        }
      }
      return;
    }
    attempts += 1;
    if (attempts > MAX_ATTEMPTS) {
      console.warn("[hoymiles] no LitElement found, cards stay disabled");
      waiting.length = 0;
      return;
    }
    timer = window.setTimeout(flush, 50);
  }

  function schedule() {
    if (timer || !waiting.length) return;
    timer = window.setTimeout(() => {
      timer = 0;
      flush();
    }, 0);
  }

  window.__hmWhenLit = function __hmWhenLit(cb) {
    if (typeof cb !== "function") return;
    const lit = window.__hmLit();
    if (lit) {
      cb(lit);
      return;
    }
    waiting.push(cb);
    attempts = 0;
    /* Nudge on every element definition: the usual trigger is Home Assistant
     * defining ``ha-card`` a few hundred milliseconds after this file runs. */
    for (const name of CANDIDATES) {
      customElements.whenDefined(name).then(() => {
        cached = null; // re-probe, the definition may not be Lit after all
        schedule();
      }).catch(() => {});
    }
    schedule();
  };

  /* ---------------------------------------------------------------------- *
   * Shared entity resolution
   *
   * ``dev_id`` is ``"<prefix>-<SN>"``, Home Assistant slugifies that into the
   * entity id, and the integration's own entities additionally carry the
   * unique id ``hoymiles_<dev_id>_<suffix>``.  The cards each carry a private
   * copy of this; the panel needs it too (to point the gauge / history cards
   * at concrete entities), so it lives here as well.
   * ---------------------------------------------------------------------- */

  function slug(value) {
    return String(value == null ? "" : value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  function norm(value) {
    return String(value == null ? "" : value).toLowerCase().replace(/[^a-z0-9]+/g, "");
  }

  /**
   * Find the entity id of ``<suffix>`` on ``dev_id``.
   *
   * Three strategies, cheapest first: the conventional
   * ``<domain>.<slug(dev_id)>_<suffix>`` id, a prefix + normalized suffix scan
   * and finally the integration's unique id.
   */
  window.__hmEntity = function __hmEntity(hass, devId, suffix, domain) {
    const dom = domain || "sensor";
    if (!hass || !hass.states || !devId) return null;

    const dev = slug(devId);
    const conventional = `${dom}.${dev}_${suffix}`;
    if (hass.states[conventional]) return conventional;

    const prefix = `${dom}.${dev}`;
    const wanted = norm(suffix);
    let found = null;
    for (const entityId of Object.keys(hass.states)) {
      if (!entityId.startsWith(prefix)) continue;
      if (norm(entityId.slice(prefix.length + 1)) !== wanted) continue;
      if (!found || entityId.length < found.length) found = entityId;
    }
    if (found) return found;

    if (hass.entities) {
      const uniqueSuffix = `hoymiles_${devId}_${suffix}`;
      for (const [entityId, entry] of Object.entries(hass.entities)) {
        if (entry && entry.unique_id === uniqueSuffix) return entityId;
      }
    }
    return null;
  };
})();
