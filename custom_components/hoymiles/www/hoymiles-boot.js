/* ============================================================================
 * Hoymiles Micro Storage — frontend entry point
 * ----------------------------------------------------------------------------
 * This is the single module Home Assistant is told to load: it is both the
 * ``module_url`` of the sidebar panel and the URL passed to
 * ``add_extra_js_url``.
 *
 * Why a bundle at all
 * -------------------
 * ``add_extra_js_url`` stores its URLs in a **set**, so the ``<script>`` order
 * in ``index.html`` is not the order the files were registered in.  Registering
 * every card separately therefore ran them in an unpredictable order, and a
 * card that executed before ``hoymiles-base.js`` could not find LitElement -
 * it waited for ``ha-panel-lovelace``, which is never defined on a custom
 * panel, and stayed unregistered for the whole page lifetime.
 *
 * Static ``import`` statements do not have that problem: ES modules evaluate
 * their dependencies in source order, before the importing module's own body.
 * So the bootstrap below always runs first, then the panel, then the cards -
 * deterministically, on every page.
 *
 * Adding a card: register it in ``const.FRONTEND_ASSETS`` (so it is served)
 * and import it here (so it is loaded).
 * ========================================================================== */

import "./hoymiles-base.js";
import "./hoymiles-panel.js";
import "./hoymiles-power-flow.js";
import "./hoymiles-energy-sankey.js";
import "./hoymiles-gauge.js";
import "./hoymiles-history-chart.js";
import "./hoymiles-battery.js";
import "./hoymiles-pack-list.js";
import "./hoymiles-control.js";
import "./hoymiles-tou-editor.js";
