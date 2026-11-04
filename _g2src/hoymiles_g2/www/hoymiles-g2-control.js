/* ============================================================================
 * Hoymiles Micro Storage — Control panel card
 * ----------------------------------------------------------------------------
 * Lovelace card: `custom:hoymiles-g2-control`
 *
 * Every command from《禾迈微储MQTT协议开发指南》V0.5.1, as buttons / inputs:
 *
 *   §10 switch      homeassistant/switch/<dev_id>/set                 ON | OFF
 *   §11 reboot      homeassistant/button/<dev_id>/reboot/trigger      RESTART
 *   §12 ems mode    homeassistant/select/<dev_id>/ems_mode/command    general |
 *                                                                     mqtt_ctrl |
 *                                                                     tou_plan
 *   §13 power ctrl  homeassistant/number/<dev_id>/power_ctrl/set      float (W)
 *   §14 output pwr  homeassistant/number/<dev_id>/output_power/set    int (W)
 *   §15 phase pwr   homeassistant/number/<dev_id>/phase_output_power/set
 *                   {"phase_a":..,"phase_b":..,"phase_c":..}
 *   §20 tou get     homeassistant/sensor/<dev_id>/tou_plan/get        {"week":..}
 *
 * Commands are published straight to those topics (qos 1, retain false), which
 * keeps the card working even when a discovery entity is missing or has a
 * narrower option list than the protocol allows. Current values are read back
 * from the matching entities when they exist.
 *
 * Card config:
 *   type: custom:hoymiles-g2-control
 *   dev_id: MSA-280520260806
 *   language: en                # optional (en|zh); omit to follow Home Assistant
 *   title: Device control
 *   show_phase: true            # optional, default true
 *   show_power_ctrl: true       # optional, default true
 *   show_log: true              # optional, default true; the MQTT log row
 *   show_topics: true           # optional, default false; show the MQTT topic
 *                               # of every row (engineering detail)
 *   subtitle: false             # optional; hide the grey line under the title
 *
 * The layout follows the iOS settings idiom: small grey section headers, one
 * rounded group per section, rows of icon + name + right-aligned control, and
 * hairline separators that stop short of the card edge. The MQTT topic paths
 * are hidden by default - they are useful while debugging but noisy in use.
 *
 * The last row of "Plan & maintenance" is an **MQTT log**, off by default. While
 * it is on the card subscribes to the device's topic tree over the Home
 * Assistant websocket (the `mqtt/subscribe` command) and streams both directions
 * in one list: what the device publishes (state topics, discovery configs, TOU
 * acknowledgements) and what Home Assistant sends to it (command topics).
 * Nothing is subscribed - and nothing is shown - while the switch is off, so the
 * card costs nothing until it is needed. `mqtt/subscribe` is an admin-only
 * command in Home Assistant, so a non-admin user sees an explanation instead of
 * a stream.
 * ========================================================================== */

function _hmControlRegister() {
  const LitElement = Object.getPrototypeOf(customElements.get("ha-panel-lovelace"));
  const html = LitElement.prototype.html;
  const css = LitElement.prototype.css;

  /* ------------------------------------------------------------------ *
   * Language
   *
   * An explicit `language:` in the card config wins. When it is absent the
   * card follows the Home Assistant user's language (`hass.language`), so a
   * dashboard matches the UI without per-card configuration. Any Chinese
   * variant counts as Chinese - Home Assistant reports `zh-Hans` / `zh-Hant`
   * and may carry a region suffix such as `zh-Hans-CN`.
   * ------------------------------------------------------------------ */
  function hmLang(hass, config) {
    const wanted = config && config.language;
    if (wanted) return String(wanted).toLowerCase().startsWith("zh") ? "zh" : "en";
    const ui = hass && hass.language;
    return ui && String(ui).toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  /* ------------------------------------------------------------------ *
   * Localised config strings
   *
   * A config value may be a plain string (used as-is, so every existing
   * dashboard keeps working) or a language map:
   *
   *   title:
   *     en: Device control
   *     zh: 设备控制
   *
   * That is what lets the text *you* write follow the UI language too, instead
   * of pinning a dashboard to one language. A map missing the current language
   * falls back to `en`, then to whichever entry exists.
   * ------------------------------------------------------------------ */
  function hmText(value, lang) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const hit = value[lang];
      if (hit != null) return hit;
      if (value.en != null) return value.en;
      const first = Object.values(value)[0];
      return first == null ? "" : first;
    }
    return value;
  }

  /** A text field can only hold a plain string, so a language map shows empty. */
  function hmField(value) {
    return typeof value === "string" ? value : "";
  }

  const EMS_MODES = [
    { id: "general", en: "General", zh: "自发自用" },
    { id: "mqtt_ctrl", en: "MQTT ctrl", zh: "MQTT 功率控制" },
    { id: "tou_plan", en: "TOU plan", zh: "分时计划" },
  ];
  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  /* Order in which the firmware publishes its `number` discovery configs. HA
   * decorates the duplicate entity ids with `_2`, `_3`, ... so this order is
   * what maps `number.<dev>_2` back to a protocol key.
   *
   * Measured, the order is NOT stable across firmware: `power_ctrl` is the base
   * entity on a storage unit and on a single-input HiFlow, but `_2` on a
   * two-input HiFlow Pro. `_resolve()` therefore tests the declared `min` first
   * and only falls back to this index, so treat this as a last resort. */
  const NUMBER_ORDER = ["power_ctrl", "output_power", "phase_output_power"];

  /* Domains where the firmware publishes exactly one entity, so "the only one on
   * this device" is a sound answer. The number domain is excluded on purpose:
   * it has several entities and a wrong pick would show - and send - the value
   * of a different setting. */
  const SINGLE_ENTITY_DOMAINS = ["select", "switch"];

  const PING_MS = 8000; // how long the "sent" confirmation stays visible

  /* Power control is a *lease*, not a setting: the firmware remembers the last
   * `power_ctrl` for about a minute and then falls back to `output_power`. A
   * single send therefore produces a burst that matches the requested wattage
   * and then silently jumps back to the output-power ceiling, which reads as
   * "the value jitters and the device ignores me". Re-publishing on a period is
   * the only way to hold it.
   *
   * That beat runs in the integration (`keepalive.py`), not here: a browser
   * timer dies the moment the dashboard is closed, which is exactly when the
   * lease still needs holding. This card only starts and stops the service and
   * reads its retained state back, so a reload shows the truth and leaving the
   * page changes nothing.
   */
  const TIMER_MIN_S = 5;
  /* 60 s is both the ceiling and the reason the timer exists: the firmware only
     holds a `power_ctrl` value for about a minute (`TIMER_LEASE_S`), so a longer
     period leaves the tail of every cycle uncontrolled. Asking for more is
     therefore meaningless, and the input clamps it back to 60 instead of
     accepting a value the device cannot honour. */
  const TIMER_MAX_S = 60;
  const TIMER_DEFAULT_S = 30;
  const TIMER_LEASE_S = 60; // the firmware's own hold time, for the hint text

  /* ------------------------------------------------------------------ *
   * MQTT log
   *
   * One wildcard subscription covers the whole topic tree of this device, so a
   * single stream carries both directions:
   *
   *   homeassistant/<component>/<dev_id>/...   firmware + integration topics
   *   hoymiles_g2/<dev_id>/...                    integration bookkeeping
   *                                            (availability, EMS mode echo)
   *
   * Direction is read off the topic: Home Assistant writes to the command side
   * (`/set`, `/command`, `/trigger`, `/get`), the device publishes everything
   * else. The `hoymiles_g2/` family is the integration's own, so it counts as
   * downlink too. This is a heuristic, but a topic cannot be told apart from
   * its payload, and the alternative (hard-coding every topic of the protocol)
   * would silently miss new ones.
   * ------------------------------------------------------------------ */
  const LOG_DOWNLINK = /\/(set|command|trigger|get)$/;
  const LOG_MAX = 200;          // entries kept (quick/state alone is one a second)
  const LOG_PAYLOAD_MAX = 1200; // characters shown per entry before truncating
  const LOG_QOS = 0;            // observing only: never add broker load

  /* Power on/off is slow: the firmware has to bring the PCS (and the packs)
     down or up again, so the card shows the requested state as pending until
     the device reports it (or gives up after this long). */
  const SWITCH_PENDING_MS = 5000;
  const SWITCH_CONFIRM_MS = 2500; // how long the tick after confirmation stays

  /* ------------------------------------------------------------------ *
   * Remembering the last command
   *
   * Three controls on this card are write-only by design: `power_ctrl`,
   * `output_power` and the power switch all publish to a `command_topic` and the
   * firmware declares no `state_topic` for any of them. Home Assistant therefore
   * has nothing to restore - those entities read `unknown` after every restart -
   * so the card used to come back blank on every visit and the whole set-up
   * (wake the unit, output power, power control, timer) had to be typed in
   * again before anything was under control.
   *
   * What the user expects to find is *what they last sent*, not what the device
   * reports, because it reports nothing. That set is remembered per device in
   * `localStorage` and restored before anything is seeded from an entity.
   *
   * The keep-alive is the one exception honoured over the cache: it runs in the
   * integration, so its `enabled` / `power` / `period` are server-side truth and
   * win over anything remembered here - see `_applyKeepalive`.
   * ------------------------------------------------------------------ */
  const STORE_PREFIX = "hoymiles-g2-control:";

  /** `localStorage` read, guarded: private-mode browsing and quotas both throw. */
  function storeGet(key) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return null;
    }
  }

  /** `localStorage` write, guarded: a full or disabled store only means the card
   * forgets, which must never break the controls. */
  function storeSet(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (err) {
      /* Deliberately silent - the toast area is for command failures. */
    }
  }

  function slug(id) {
    return String(id).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  }

  function norm(name) {
    return String(name).toLowerCase().replace(/[^a-z0-9]+/g, "");
  }

  /* Protocol keys and the names Home Assistant derives entity ids from do not
   * always agree on abbreviations: the protocol says `power_ctrl`, the entity is
   * called "Power Control Keep-alive". Folding `ctrl` into `control` before
   * comparing lets both spellings match without an alias table. */
  function normKey(name) {
    return norm(name).replace(/ctrl/g, "control");
  }

  function num(value) {
    if (typeof value === "number") return Number.isFinite(value) ? value : 0;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  /* `esc()` is only for markup strings handed to `_untrusted()` (they go through
   * `innerHTML`). Lit templates escape their own bindings, so a `${...}` inside a
   * `html` template must keep the value raw. */

  class HoymilesControl extends LitElement {
    static get properties() {
      return {
        _config: { type: Object },
        _hass: { type: Object },
        _powerCtrl: { type: String },
        _outputPower: { type: String },
        _phase: { type: Object },
        _week: { type: String },
        _toast: { type: String },
        _toastError: { type: Boolean },
        _optimistic: { type: Object },
        _logOpen: { type: Boolean },
        _timerOn: { type: Boolean },
        _timerPeriod: { type: String },
        _timerCount: { type: Number },
        _timerLastAt: { type: Number },
        _timerError: { type: String },
        _timerBusy: { type: Boolean },
        /* The wattage the running beat is holding. Kept separately from
           `_powerCtrl` because the slider is an input in flight, not a
           statement of what the device is doing. */
        _timerPower: { type: Number },
      };
    }

    constructor() {
      super();
      this._hass = null;
      this._config = null;
      this._powerCtrl = "";
      this._outputPower = "";
      this._phase = { a: "", b: "", c: "" };
      this._week = "Mon";
      this._toast = "";
      this._toastError = false;
      this._optimistic = {};
      this._cache = new Map();
      this._initialised = false;
      this._toastTimer = null;
      /* Power switch: the requested target while it is in flight, and the time
         the device confirmed it (drives the tick + spinner). */
      this._switchPending = null;
      this._switchConfirmedAt = 0;
      this._pendingTimer = null;
      /* MQTT log. The entries live in `_log` (the source of truth) and are
         appended to the DOM by hand - see `_syncLogDom` for why. */
      this._logOpen = false;
      this._log = [];
      this._logDropped = 0;
      this._logErr = "";
      this._logList = null;
      this._logUnsubs = [];
      this._logGen = 0;
      /* Periodic re-send of the power-control lease, mirrored from the
         integration. The card never owns the beat: it starts the service and
         then follows the retained state topic, so the switch stays correct after
         a reload and leaving the dashboard stops nothing. */
      this._timerOn = false;
      this._timerPeriod = String(TIMER_DEFAULT_S);
      this._timerCount = 0;
      this._timerLastAt = 0;
      this._timerError = "";
      this._timerBusy = false;
      this._timerPower = NaN;
    }

    static getConfigElement() {
      return document.createElement("hoymiles-g2-control-editor");
    }

    static getStubConfig() {
      return { dev_id: "" };
    }

    static get styles() {
      return css`
        /* iOS-style settings layout: grouped cards, right-aligned controls,
           hairline separators that stop short of the card edge. */
        :host { display: block; }
        ha-card { padding: 14px 16px 16px; }
        .head { display: flex; align-items: baseline; gap: 10px;
                flex-wrap: wrap; margin-bottom: 12px; }
        .head .title { font-size: 17px; font-weight: 600;
                       color: var(--primary-text-color); }
        .head .sub { font-size: 12.5px; color: var(--secondary-text-color); }

        .group { background: var(--secondary-background-color, rgba(120,120,128,.08));
                 border-radius: 14px; overflow: hidden; margin-bottom: 14px; }
        .group-title { font-size: 12.5px; font-weight: 500;
                       color: var(--secondary-text-color);
                       padding: 0 6px 6px; }
        .group-wrapper:not(:first-of-type) { margin-top: 16px; }

        .item { display: flex; align-items: center; gap: 12px;
                padding: 11px 14px; min-height: 52px;
                box-sizing: border-box; position: relative; }
        /* The group clips its content (overflow: hidden), so a row that does not
           fit has to wrap instead of spilling: when the card is narrow the
           control moves to its own line below the label. Without this the
           segmented control was cut off once the dashboard column shrank. */
        .item:not(.stack) { flex-wrap: wrap; }
        .item + .item::before {
          content: ""; position: absolute; top: 0; left: 14px; right: 0;
          height: 1px; background: var(--divider-color); opacity: .7;
        }
        .item .ico { flex: 0 0 auto; width: 24px; text-align: center;
                     font-size: 16px; line-height: 1; }
        .item .nm { flex: 1 1 auto; min-width: 0; font-size: 15px;
                    color: var(--primary-text-color); line-height: 1.3; }
        /* Row layout only: giving the label a real basis keeps it readable and
           makes the control wrap first instead of squeezing the label to 0. */
        .item:not(.stack) .nm { flex: 1 1 7.5em; }
        .item .nm small { display: block; font-size: 12px; font-weight: 400;
                          color: var(--secondary-text-color); margin-top: 2px;
                          line-height: 1.35; }
        .item .nm code { font-size: 11px; color: var(--secondary-text-color);
                         word-break: break-all; }
        .item .ctrl { flex: 0 1 auto; display: flex; align-items: center;
                      gap: 8px; margin-left: auto;
                      flex-wrap: wrap; justify-content: flex-end;
                      max-width: 100%; }
        .item.stack { flex-direction: column; align-items: stretch; gap: 8px; }
        .item.stack .ctrl { margin-left: 0; flex: 0 0 auto;
                            flex-wrap: wrap; justify-content: flex-start; }
        .item .ctrl .unit { font-size: 13px; color: var(--secondary-text-color); }

        /* segmented control (the iOS signature control) */
        .seg { display: inline-flex; padding: 2px; gap: 2px;
               max-width: 100%; flex-wrap: wrap;
               background: var(--secondary-background-color, rgba(120,120,128,.16));
               border-radius: 10px; }
        .seg button {
          border: none; background: none; font: inherit; font-size: 13px;
          padding: 5px 12px; border-radius: 8px; cursor: pointer;
          color: var(--primary-text-color); white-space: nowrap;
          transition: background .15s, box-shadow .15s;
        }
        .seg button.on {
          background: var(--card-background-color, #fff);
          box-shadow: 0 1px 3px rgba(0,0,0,.14); font-weight: 600;
        }
        .seg button:disabled { opacity: .4; cursor: not-allowed; }
        .seg.danger button.on { color: var(--error-color); }

        /* In-flight power on/off: the pressed option spins a ring until the
           device reports the new state. The spinner lives in the button's own
           ::after, so no extra markup is needed over the segment. */
        .seg button.pending { padding-right: 24px; position: relative; }
        .seg button.pending::after {
          content: ""; position: absolute; top: 50%; right: 7px;
          width: 9px; height: 9px; margin-top: -5.5px; border-radius: 50%;
          border: 2px solid currentColor; border-top-color: transparent;
          opacity: .75; animation: hm-spin .7s linear infinite;
        }
        @keyframes hm-spin { to { transform: rotate(360deg); } }

        /* The sub-line carries the progress, so a slow power cycle still has
           visible feedback right where the user is looking. */
        .item .nm small.busy { color: var(--primary-color);
                               animation: hm-pulse 1.3s ease-in-out infinite; }
        .item .nm small.done { color: var(--success-color, #0da035);
                               font-weight: 500; }
        /* The re-send timer runs indefinitely, so it gets a steady tint -
           "busy" above pulses and would blink for as long as the switch is on. */
        .item .nm small.ticking { color: var(--primary-color); font-weight: 500; }
        @keyframes hm-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }

        /* plain pill button */
        .btn {
          font: inherit; font-size: 13.5px; font-weight: 500;
          padding: 8px 15px; border-radius: 10px; border: none;
          cursor: pointer; background: var(--secondary-background-color, rgba(120,120,128,.16));
          color: var(--primary-text-color); transition: filter .15s;
        }
        .btn:active { filter: brightness(.94); }
        .btn.primary { background: var(--primary-color);
                       color: var(--text-primary-color, #fff); font-weight: 600; }
        .btn.danger { background: none; color: var(--error-color); padding: 8px 10px; }
        .btn:disabled { opacity: .45; cursor: not-allowed; }

        /* editable read-out next to a slider */
        input[type="number"] {
          font: inherit; font-size: 15px; width: 78px; text-align: right;
          padding: 7px 10px; border-radius: 10px;
          border: 1px solid transparent;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color); outline: none;
          font-variant-numeric: tabular-nums;
        }
        input[type="number"]:focus { border-color: var(--primary-color); }
        input[type="number"].narrow { width: 58px; }

        /* iOS slider: hairline track with a tinted fill and a white round knob.
           The --pct custom property is set inline from the value, so the fill
           follows the knob without needing a second element.
           NOTE: never write a backtick inside this css template (not even in a
           comment) - it would terminate the template string. */
        .slider { display: flex; align-items: center; gap: 10px;
                  width: 100%; flex-wrap: wrap; }
        .slider.end { justify-content: flex-end; }
        .slider .tag { flex: 0 0 auto; width: 12px; font-size: 13px;
                       color: var(--secondary-text-color); }
        input[type="range"] {
          -webkit-appearance: none;
          appearance: none;
          flex: 1 1 auto; min-width: 90px; height: 4px; margin: 0;
          border-radius: 2px; outline: none; cursor: pointer;
          background: linear-gradient(90deg,
            var(--primary-color) 0 var(--pct, 0%),
            var(--divider-color) var(--pct, 0%) 100%);
        }
        input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none; appearance: none;
          width: 22px; height: 22px; border-radius: 50%;
          background: #fff; border: none; cursor: grab;
          box-shadow: 0 1px 4px rgba(0,0,0,.25), 0 0 0 .5px rgba(0,0,0,.08);
        }
        input[type="range"]::-webkit-slider-thumb:active { cursor: grabbing; }
        input[type="range"]::-moz-range-thumb {
          width: 22px; height: 22px; border-radius: 50%;
          background: #fff; border: none;
          box-shadow: 0 1px 4px rgba(0,0,0,.25);
        }
        input[type="range"]:disabled { opacity: .45; cursor: not-allowed; }
        input[type="range"]:disabled::-webkit-slider-thumb { cursor: not-allowed; }
        select {
          font: inherit; font-size: 15px; padding: 7px 10px;
          border-radius: 10px; border: 1px solid transparent;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color); outline: none; cursor: pointer;
        }
        select:focus { border-color: var(--primary-color); }
        .state { font-size: 13px; color: var(--secondary-text-color);
                 white-space: nowrap; }
        .state.live { color: var(--primary-color); font-weight: 500; }

        /* Device read-back chips: label + value pairs, wrapped so a narrow
           column stacks them instead of clipping the last one. */
        .chip {
          display: inline-flex; align-items: baseline; gap: 5px;
          font-size: 13px; line-height: 1.6;
          padding: 2px 9px; border-radius: 999px;
          font-variant-numeric: tabular-nums;
          background: var(--secondary-background-color, rgba(120,120,128,.14));
          color: var(--primary-text-color);
        }
        .chip b { font-size: 11px; font-weight: 500; letter-spacing: .02em;
                  color: var(--secondary-text-color); text-transform: uppercase; }
        .chip.pv { background: rgba(34,197,94,.16); }
        .chip.grid { background: rgba(34,211,238,.16); }
        .chip.load { background: rgba(245,166,35,.16); }
        .chip.mode { background: rgba(120,120,128,.22); }

        /* MQTT log. It sits inside the "Plan & maintenance" group, directly
           under its own row, and grows downwards - the panel itself is the
           scroll container so the card never jumps. */
        .log-block { border-top: 1px solid var(--divider-color); }
        .log-head { display: flex; align-items: center; gap: 8px;
                    flex-wrap: wrap; padding: 10px 14px 6px; }
        .log-head .log-title { font-size: 12.5px; font-weight: 500;
                               color: var(--primary-text-color); }
        .log-head .log-count { font-size: 12px; margin-right: auto;
                               color: var(--secondary-text-color);
                               font-variant-numeric: tabular-nums; }
        .log-list { display: flex; flex-direction: column; gap: 6px;
                    max-height: 340px; overflow: auto; padding: 0 14px 8px; }
        .log-row { font-size: 12px; border-radius: 10px; padding: 6px 8px;
                   background: var(--secondary-background-color, rgba(120,120,128,.10)); }
        .log-row .log-meta { display: flex; align-items: center; gap: 6px;
                             flex-wrap: wrap; }
        .log-row .log-time { color: var(--secondary-text-color);
                             font-variant-numeric: tabular-nums; }
        .log-row .log-dir { font-size: 11px; line-height: 1.5;
                            padding: 0 6px; border-radius: 999px;
                            background: rgba(120,120,128,.20);
                            color: var(--secondary-text-color); }
        .log-row.down .log-dir { background: rgba(3,169,244,.16);
                                 color: var(--primary-color); }
        .log-row .log-topic { font-family: ui-monospace, SFMono-Regular, Menlo,
                              Consolas, monospace; word-break: break-all;
                              color: var(--primary-text-color); }
        /* The device id repeats on every line; dimming it keeps the paths easy
           to scan. It is still part of the text, so a selection copies the
           real topic. */
        .log-row .log-topic .log-dev { color: var(--secondary-text-color); }
        /* No max-height, no overflow: the payload grows the row and the list is
           the single scroll region. The old inner scrollbar meant two nested
           scrollbars whenever a payload was long. */
        .log-row pre.log-payload { margin: 4px 0 0; white-space: pre-wrap;
                                   word-break: break-all; line-height: 1.45;
                                   font-size: 11.5px;
                                   font-family: ui-monospace, SFMono-Regular, Menlo,
                                   Consolas, monospace;
                                   color: var(--secondary-text-color); }
        .log-hint { padding: 0 14px 10px; font-size: 12px;
                    color: var(--secondary-text-color); }
        .log-hint.err { color: var(--error-color); }
        .btn.small { padding: 5px 10px; font-size: 12.5px; }
        .toast { margin-top: 12px; font-size: 13px; padding: 10px 13px;
                 border-radius: 12px;
                 background: var(--secondary-background-color, rgba(120,120,128,.12)); }
        .toast.err { color: var(--error-color); }
      `;
    }

    setConfig(config) {
      if (!config || !config.dev_id) {
        throw new Error("hoymiles-g2-control: 'dev_id' is required");
      }
      const changed = this._config && this._config.dev_id !== config.dev_id;
      this._config = { ...config };
      this._cache.clear();
      this._initialised = false;
      /* A different device means different topics, so the open log has to let
         go of the old ones. Closing it is friendlier than silently subscribing
         to the new device: the user asked for that view. */
      if (changed && this._logOpen) this._closeLog();
      /* A different device means different topics. The keep-alive belongs to the
         old device and must not be stopped for it (the user may still want it
         running), so this only drops the local mirror and re-reads the new
         device's own state. */
      if (changed) {
        this._timerOn = false;
        this._timerCount = 0;
        this._timerLastAt = 0;
        this._timerError = "";
        this._timerPower = NaN;
        this._timerPeriod = String(TIMER_DEFAULT_S);
        /* The saved set is per device, so switching device must also drop the
           restored switch / EMS command - they belonged to the previous unit. */
        delete this._optimistic.switch;
        delete this._optimistic.ems_mode;
      }
    }

    set hass(hass) {
      this._hass = hass;
      if (!this._initialised) this._seedInputs();
      this._reconcileSwitch();
      /* The beat runs in the integration, so its running state arrives as an
         entity state - reading it here means every update re-syncs the row for
         free, and a card opened after the fact shows the truth immediately. */
      this._syncKeepalive();
      this.requestUpdate();
    }

    getCardSize() {
      return 13;
    }

    connectedCallback() {
      super.connectedCallback();
      /* Dashboards disconnect cards when a view is left; coming back with the
         log still switched on must resume the stream. The guard also keeps a
         re-connect from subscribing twice. */
      if (this._logOpen && !this._logUnsubs.length) this._subscribeLog();
    }

    disconnectedCallback() {
      super.disconnectedCallback();
      if (this._toastTimer) clearTimeout(this._toastTimer);
      if (this._pendingTimer) clearTimeout(this._pendingTimer);
      this._unsubscribeLog();
      /* Deliberately nothing here stops the keep-alive: the whole point of
         moving it into the integration is that leaving the dashboard (or
         closing the browser) must not drop the power limit. Stop it from the
         row's own Off button, the stop service, or an automation. */
    }

    updated() {
      this._syncLogDom();
    }

    /* ----------------------------- lookups ----------------------------- */

    _t(en, zh) {
      return hmLang(this._hass, this._config) === "zh" ? zh : en;
    }

    /** Resolve one user-supplied string (plain string or language map). */
    _text(value) {
      return hmText(value, hmLang(this._hass, this._config));
    }

    _dev() {
      return this._config.dev_id;
    }

    /**
     * Resolve an entity by protocol key.
     *
     * The firmware's MQTT discovery uses `<dev_id>_<key>` unique ids, while the
     * integration's own entities use `hoymiles_g2_<dev_id>_<key>`; entity ids are
     * slugified from the *name*, so they are matched normalized.
     */
    /**
     * Entity ids the card config pins to some *other* protocol key.
     *
     * `power_ctrl` and `output_power` are both plain `number` entities of the
     * same device, so every heuristic below can hand the same entity to both.
     * A config that pins `output_power: number.<dev>` therefore made the
     * `power_ctrl` row read that very entity - showing the output power's
     * range and step on the power control row, and (worse) letting one row's
     * declared bounds describe the other's setting. An explicit pin is the
     * one authoritative signal the frontend actually gets, so an entity
     * claimed by another key is excluded from every guess here.
     */
    _claimedByOther(key) {
      const overrides = this._config.entities || {};
      const claimed = new Set();
      for (const [other, entityId] of Object.entries(overrides)) {
        if (other !== key && typeof entityId === "string" && entityId) {
          claimed.add(entityId);
        }
      }
      claimed.delete(overrides[key]);
      return claimed;
    }

    _resolve(key, domain = "number") {
      const overrides = this._config.entities || {};
      if (overrides[key]) return overrides[key];

      const hass = this._hass;
      if (!hass || !hass.states) return null;

      const claimed = this._claimedByOther(key);
      const cacheKey = `${domain}:${key}`;
      const cached = this._cache.get(cacheKey);
      if (cached && hass.states[cached] && !claimed.has(cached)) return cached;

      let found = null;
      const wantUid = new Set([
        `${this._dev()}_${key}`,
        `hoymiles_g2_${this._dev()}_${key}`,
      ]);
      for (const [entityId, entry] of Object.entries(hass.entities || {})) {
        if (!entry || !entityId.startsWith(`${domain}.`)) continue;
        if (claimed.has(entityId)) continue;
        if (wantUid.has(entry.unique_id)) { found = entityId; break; }
      }

      if (!found) {
        const prefix = `${domain}.${slug(this._dev())}`;
        const wanted = norm(key);
        for (const entityId of Object.keys(hass.states)) {
          if (!entityId.startsWith(prefix)) continue;
          if (claimed.has(entityId)) continue;
          const tail = norm(entityId.slice(prefix.length + 1));
          if (tail !== wanted) continue;
          if (!found || entityId.length < found.length) found = entityId;
        }
      }

      /* Device-scoped tail match: "the entity of this device whose id ends with
       * the protocol key". This is what survives a renamed entity - the id may
       * pick up an area prefix (`wo_shi_...`) or spell `ctrl` out as `control`,
       * but the tail still names the setting. Scoped to the device, so a match
       * can never cross over to another inverter. */
      if (!found) {
        const wanted = normKey(key);
        const scoped = this._deviceEntityIds(domain)
          .filter((entityId) => !claimed.has(entityId))
          .filter((entityId) => normKey(entityId).endsWith(wanted));
        if (scoped.length === 1) found = scoped[0];
        else if (scoped.length > 1) {
          // Prefer the shortest id: a rename adds prefixes, it does not shorten.
          scoped.sort((a, b) => a.length - b.length || a.localeCompare(b));
          found = scoped[0];
        }
      }

      // The firmware's own number entities are unhelpfully named: the MQTT
      // discovery topics carry the object id (power_ctrl / output_power /
      // phase_output_power) but HA names all three after the device, so their
      // entity ids collapse to `number.<dev>`, `number.<dev>_2`, `_3 ...` and
      // neither the friendly name nor the registry snapshot distinguishes them
      // (HA does not expose unique_id to the frontend).
      //
      // The duplicate suffix order is *not* stable across firmware: measured,
      // `power_ctrl` is the base entity on a storage unit (min -2500, step 0.1)
      // and on a single-input HiFlow (min 0, cap 132), but `_2` on a two-input
      // HiFlow Pro (min 0, step 0.1) - whose base is `output_power` (min 100).
      // So a fixed index picks the wrong entity on two of the three models.
      //
      // What *is* stable is the declared range: the firmware gives `power_ctrl`
      // a floor at or below zero (it can curtail to nothing, and on a storage
      // unit also charge/export negative), while `output_power` starts at the
      // hardware minimum, 100 W on every model measured. Resolve by bounds when
      // exactly one candidate fits and only fall back to the index otherwise.
      // `entities` in the card config overrides all of this.
      if (!found && domain === "number") {
        const index = NUMBER_ORDER.indexOf(key);
        if (index >= 0) {
          const base = `${domain}.${slug(this._dev())}`;
          // `number.<dev>`, `number.<dev>_2`, `number.<dev>_3`, ...
          // The device SN is numeric too, so the duplicate suffix must be short
          // (`_2`), never the SN itself (`number.<dev>_280520260806`).
          const numbered = Object.keys(hass.states).filter((entityId) => {
            if (claimed.has(entityId)) return false;
            if (entityId === base) return true;
            return new RegExp(`^${base.replace(/\./g, "\\.")}_\\d{1,2}$`).test(entityId);
          });
          const order = (entityId) => {
            if (entityId === base) return 0;
            const m = entityId.match(/_(\d+)$/);
            return m ? Number(m[1]) : Number.MAX_SAFE_INTEGER;
          };
          numbered.sort((a, b) => order(a) - order(b));

          const declaredMin = (entityId) => {
            const state = hass.states[entityId];
            const value = state && state.attributes ? state.attributes.min : null;
            return value == null ? null : num(value);
          };
          let picked = null;
          if (key === "power_ctrl") {
            // `min <= 0` is `power_ctrl` and nothing else.
            const zeroFloor = numbered.filter((entityId) => {
              const lo = declaredMin(entityId);
              return lo != null && Number.isFinite(lo) && lo <= 0;
            });
            if (zeroFloor.length === 1) [picked] = zeroFloor;
          } else if (key === "output_power") {
            // `min > 0` narrows it down to the rated-output entities, which at
            // least removes `power_ctrl` from the pool.
            const ratedFloor = numbered.filter((entityId) => {
              const lo = declaredMin(entityId);
              return lo != null && Number.isFinite(lo) && lo > 0;
            });
            if (ratedFloor.length === 1) [picked] = ratedFloor;
          }
          if (!picked && numbered[index]) picked = numbered[index];
          if (picked) found = picked;
        }
      }

      // Last resort for the single-instance domains: the discovery name does not
      // always map back to the protocol key (`ems_mode` is published as
      // `select.<dev>_mqtt_select`, and the switch as `<dev>_mqtt_switch`). Those
      // domains carry exactly one entity per device, so there is nothing to guess.
      // `number` is deliberately excluded - it has several entities and a wrong
      // pick would display (and send) a different setting's value.
      if (!found && SINGLE_ENTITY_DOMAINS.includes(domain)) {
        const prefix = `${domain}.${slug(this._dev())}`;
        const candidates = Object.keys(hass.states)
          .filter((entityId) => entityId.startsWith(prefix));
        if (candidates.length === 1) found = candidates[0];
      }

      if (found) this._cache.set(cacheKey, found);
      return found;
    }

    _state(key, domain = "number") {
      const entityId = this._resolve(key, domain);
      if (!entityId || !this._hass) return null;
      const state = (this._hass.states || {})[entityId];
      if (!state) return null;
      const value = String(state.state);
      if (value === "" || value === "unknown" || value === "unavailable") return null;
      return state;
    }

    _number(key) {
      const state = this._state(key, "number");
      return state ? num(state.state) : null;
    }

    /* Declared attributes survive an unusable state, the value does not.
     *
     * `min` / `max` / `step` / `options` are part of the entity's declaration and
     * are present even while its state reads `unknown` - which is exactly the
     * situation right after setup, before the device has accepted a command (a
     * number entity whose firmware publishes no state topic stays `unknown`
     * indefinitely). Reading them through `_state()` therefore threw the range
     * away and every consumer fell back to the protocol default, so a HiFlow Pro
     * whose firmware declares `100 ~ 1000 W` offered `100 ~ 2000 W` - a range the
     * device rejects. The value lookup keeps the strict filter, because a stale
     * number is worse than no number.
     */
    _attr(key, domain, name) {
      const entityId = this._resolve(key, domain);
      if (!entityId || !this._hass || !this._hass.states) return null;
      const state = this._hass.states[entityId];
      if (!state || !state.attributes) return null;
      const value = state.attributes[name];
      return value === undefined ? null : value;
    }

    /** True when this device actually has that entity.
     *
     * The integration only creates the entities a model implements (it gates on
     * the capabilities the firmware declares), so a missing entity is a reliable
     * "this device has no such feature" signal - much better than guessing from
     * the model name. Rows backed by a missing entity are dropped instead of
     * being rendered as controls that quietly do nothing.
     */
    _hasEntity(key, domain) {
      return this._resolve(key, domain) != null;
    }

    /** Entity ids the registry attributes to *this* device.
     *
     * `hass.entities` does expose `device_id`, and `hass.devices` carries the
     * device's identifiers, so the device can be found from the configured
     * `dev_id` even when the entity was renamed. That matters: a user-renamed
     * entity keeps its `unique_id` but gets a new entity id, and the frontend
     * registry snapshot does not ship `unique_id` at all - so neither guessing
     * the id nor matching on unique_id works after a rename. The device link is
     * the only stable join.
     */
    _deviceEntityIds(domain) {
      const hass = this._hass;
      if (!hass || !hass.entities || !hass.devices) return [];

      const wanted = String(this._dev()).toLowerCase();
      let deviceId = null;
      for (const [id, device] of Object.entries(hass.devices)) {
        const ids = (device && device.identifiers) || [];
        for (const pair of ids) {
          if (!Array.isArray(pair) || pair.length < 2) continue;
          if (String(pair[0]).toLowerCase() !== "hoymiles_g2") continue;
          if (String(pair[1]).toLowerCase() === wanted) { deviceId = id; break; }
        }
        if (deviceId) break;
      }
      if (!deviceId) return [];

      const out = [];
      for (const [entityId, entry] of Object.entries(hass.entities)) {
        if (!entry || entry.device_id !== deviceId) continue;
        if (domain && !entityId.startsWith(`${domain}.`)) continue;
        if (!hass.states || !hass.states[entityId]) continue;
        out.push(entityId);
      }
      return out;
    }

    _topic(suffix) {
      return `homeassistant/${suffix.replace("<dev_id>", this._dev())}`;
    }

    /** Pre-fill the inputs from the device the first time we see it.
     *
     * Values are clamped to the entity's own range: an unconfigured entity often
     * reports `0`, which is outside e.g. output_power's `100 ~ 2000 W`. Without
     * the clamp the slider would sit at its minimum while the read-out showed the
     * out-of-range number, and the two would disagree.
     *
     * Order matters and is the whole point of the persisted cache:
     *
     * 1. what this browser last sent (`_restore`) - the write-only controls have
     *    no entity value to speak of, so this is normally the only source;
     * 2. what the entity reports, when it has a usable value;
     * 3. the clamp against the entity's declared bounds either way.
     *
     * The earlier version returned early unless the entity had a value, and with
     * both `number` entities permanently `unknown` that meant nothing was ever
     * seeded and the sliders stayed at their defaults - the exact "I have to set
     * everything again" complaint.
     */
    _seedInputs() {
      if (!this._hass || !this._hass.states) return;
      const saved = this._restore();
      const pc = this._number("power_ctrl");
      const op = this._number("output_power");
      let any = false;
      const pick = (live, remembered) => {
        if (live != null) return { value: live, from: "live" };
        if (Number.isFinite(remembered)) return { value: remembered, from: "saved" };
        return null;
      };
      const pcPick = pick(pc, saved.power_ctrl);
      if (pcPick) {
        const b = this._bounds("power_ctrl", -1000, 1000);
        const { lo, hi } = this._powerRange(b.lo, b.hi);
        this._powerCtrl = String(this._clamp(pcPick.value, lo, hi));
        any = true;
      }
      const opPick = pick(op, saved.output_power);
      if (opPick) {
        const b = this._bounds("output_power", 100, 2000);
        this._outputPower = String(this._clamp(opPick.value, b.lo, b.hi));
        any = true;
      }
      /* Nothing was ever sent for power control: start it at the output power,
         which is the wattage the device already holds by default. Leaving the
         slider empty made the row read "0 W" on a unit that was producing, and
         it is never a value anyone wants to keep. */
      if (!pcPick && opPick) {
        const b = this._bounds("power_ctrl", -1000, 1000);
        const { lo, hi } = this._powerRange(b.lo, b.hi);
        this._powerCtrl = String(this._clamp(opPick.value, lo, hi));
      }
      const phases = ["a", "b", "c"];
      let anyPhase = false;
      for (const p of phases) {
        const live = this._number(`phase_${p}_output_power`)
          ?? this._number("phase_output_power");
        const remembered = saved.phase ? Number(saved.phase[p]) : NaN;
        const use = live != null ? live : remembered;
        if (Number.isFinite(use)) {
          const b = this._bounds("phase_a_output_power", 100, 2500);
          this._phase[p] = String(this._clamp(use, b.lo, b.hi));
          anyPhase = true;
        }
      }
      any = any || anyPhase;
      /* The switch command is remembered even though the user cannot see it on
         an entity: restoring it makes the segment show 开机 / 关机 as chosen
         instead of falling back to "no command sent yet". */
      if (saved.switch === "on" || saved.switch === "off") {
        this._optimistic.switch = saved.switch;
        any = true;
      }
      if (saved.ems_mode) {
        this._optimistic.ems_mode = saved.ems_mode;
        any = true;
      }
      if (Number.isFinite(saved.timer_period)) {
        this._timerPeriod = String(this._clampPeriod(saved.timer_period));
        any = true;
      }
      if (!any) return; // nothing to seed yet
      this._initialised = true;
    }

    /** The remembered command set for this device, or `{}`. */
    _remembered() {
      const raw = storeGet(`${STORE_PREFIX}${this._dev()}`);
      return raw && typeof raw === "object" ? raw : {};
    }

    /**
     * Load the remembered set into the fields this card controls.
     *
     * Returns only the numeric values: the date stamp and the switch value are
     * handled separately, because the switch must not be restored as an
     * "in-flight" command (it was sent long ago and is not awaiting anything).
     */
    _restore() {
      const raw = this._remembered();
      const out = {
        power_ctrl: Number(raw.power_ctrl),
        output_power: Number(raw.output_power),
        timer_period: Number(raw.timer_period),
        switch: raw.switch,
        ems_mode: raw.ems_mode,
        phase: raw.phase && typeof raw.phase === "object" ? raw.phase : null,
      };
      /* A remembered value outside the entity's present bounds is dropped rather
         than clamped: the range can shrink after a firmware update, and silently
         pinning a stale 700 W to a device now capped at 132 W would be a lie
         about what was sent. `_seedInputs` clamps whatever survives. */
      return out;
    }

    /**
     * Persist the last command of one control.
     *
     * Called from the send paths, never from the render path: a slider drag is
     * an input in flight, and remembering it would make the card reopen on a
     * value that was never sent.
     */
    _remember(patch) {
      const key = `${STORE_PREFIX}${this._dev()}`;
      const prev = this._remembered();
      storeSet(key, { ...prev, ...patch, at: Date.now() });
    }

    /* ------------------------------ sending ------------------------------ */

    async _publish(topic, payload, label, opts) {
      if (!this._hass || typeof this._hass.callService !== "function") return;
      /* `quiet` suppresses the success toast only. The timer repeats the same
         command every few seconds, and a toast each time would cover the card
         permanently - its progress lives on the row's own sub-line instead. A
         failure is still reported, because that is exactly what must not pass
         unnoticed. */
      const quiet = Boolean(opts && opts.quiet);
      try {
        await this._hass.callService("mqtt", "publish", {
          topic,
          payload: typeof payload === "string" ? payload : JSON.stringify(payload),
          qos: 1,
          retain: false,
        });
        if (!quiet) this._showToast(`${this._t("Sent", "已下发")} ${label} → ${topic}`);
      } catch (err) {
        this._showToast(`${this._t("Failed", "下发失败")}: ${topic} (${err.message || err})`, true);
      }
    }

    _showToast(message, isError = false) {
      this._toast = message;
      this._toastError = isError;
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        this._toast = "";
        this.requestUpdate();
      }, PING_MS);
    }

    /** Clock seam, so the harness can drive the pending timeouts. */
    _now() {
      return Date.now();
    }

    _setSwitch(on) {
      const target = on ? "on" : "off";
      if (this._switchTarget() === target) return; // already on the way there
      this._optimistic.switch = target;
      /* Remembered so a reload shows 开机 / 关机 as chosen: the switch entity is
         optimistic and no state topic exists, so there is nothing else to
         restore from. */
      this._remember({ switch: target });
      this._switchPending = { target, at: this._now() };
      this._switchConfirmedAt = 0;
      // Wake up once the wait is over, so the UI falls back to the real state
      // even when the device never answers (no hass push would do it for us).
      if (this._pendingTimer) clearTimeout(this._pendingTimer);
      this._pendingTimer = setTimeout(() => {
        this._pendingTimer = null;
        this.requestUpdate();
      }, SWITCH_PENDING_MS + 100);
      this.requestUpdate();
      this._publish(this._topic("switch/<dev_id>/set"), on ? "ON" : "OFF",
        this._t(on ? "Power on" : "Power off", on ? "开机" : "关机"));
    }

    /** The requested target while the command is still in flight. */
    _switchTarget() {
      const pending = this._switchPending;
      if (!pending) return null;
      if (this._now() - pending.at >= SWITCH_PENDING_MS) return null;
      return pending.target;
    }

    /** The device's own state, or null when it does not report one. */
    _switchReal() {
      const state = this._state("mqtt_switch", "switch") || this._state("config", "switch");
      const value = state ? String(state.state) : null;
      if (value === "on" || value === "off") return value === "on";
      return null;
    }

    /**
     * True when the entity cannot confirm its own state.
     *
     * The firmware's discovery switch is patched into an optimistic entity
     * (`assumed_state`, no `state_topic`), because its original state topic is a
     * nested JSON blob that never equals ON/OFF. HA then only remembers the last
     * command *it* sent - it never learns what the device actually did. Waiting
     * for a confirmation would always time out, and falling back to HA's value
     * after the timeout would snap the button back to the previous state, which
     * reads as "the command failed".
     */
    _switchOptimistic() {
      const state = this._state("mqtt_switch", "switch") || this._state("config", "switch");
      return Boolean(state && state.attributes && state.attributes.assumed_state);
    }

    /**
     * Drop the pending marker once the device agrees (or the wait expires).
     *
     * Called from the `hass` setter, i.e. on every push, which is what makes the
     * spinner turn into a tick as soon as the firmware confirms the new state.
     */
    _reconcileSwitch() {
      const pending = this._switchPending;
      if (!pending) return;
      if (this._now() - pending.at >= SWITCH_PENDING_MS) {
        this._switchPending = null;
        return;
      }
      // An optimistic entity cannot confirm anything, so only the timeout ends
      // the pending state (the requested value then simply stays in force).
      if (this._switchOptimistic()) return;
      const real = this._switchReal();
      if (real !== null && real === (pending.target === "on")) {
        this._switchPending = null;
        this._switchConfirmedAt = this._now();
        if (this._pendingTimer) {
          clearTimeout(this._pendingTimer);
          this._pendingTimer = null;
        }
        // Fade the tick away on its own.
        this._pendingTimer = setTimeout(() => {
          this._pendingTimer = null;
          this.requestUpdate();
        }, SWITCH_CONFIRM_MS + 100);
      }
    }

    /** { on, pending, justConfirmed, optimistic, commanded } for the switch row. */
    _switchView() {
      const target = this._switchTarget();
      /* `optimistic` and `commanded` travel with the view because the row has to
         word itself differently in the two cases: "已休眠" is a claim about the
         device, and for an optimistic entity nothing about the device is known. */
      if (target) {
        return {
          on: target === "on", pending: target, confirmed: false,
          optimistic: this._switchOptimistic(), commanded: true,
        };
      }
      const real = this._switchReal();
      /* A command issued from this card is authoritative for an optimistic
         entity: HA only remembers the commands it sent itself, so waiting for
         (or falling back to) that value would snap the button back. Before any
         such command the entity's value is still the best thing we have, and for
         a real entity the device always wins. */
      const mine = this._optimistic.switch;
      const commanded = mine === "on" || mine === "off";
      const on = this._switchOptimistic() && commanded
        ? mine === "on"
        : real !== null
          ? real
          : mine === "on";
      const justConfirmed = this._switchConfirmedAt > 0
        && this._now() - this._switchConfirmedAt < SWITCH_CONFIRM_MS;
      if (!justConfirmed) this._switchConfirmedAt = 0;
      return {
        on, pending: null, confirmed: justConfirmed,
        optimistic: this._switchOptimistic(), commanded,
      };
    }

    _isSwitchOn() {
      return this._switchView().on;
    }

    /* --------------------------- device read-back --------------------------- */

    /**
     * The device's own numbers, as opposed to what this card last commanded.
     *
     * This distinction is the whole reason the read-back row exists. Two of the
     * controls above are write-only by design:
     *
     * * `power_ctrl` and `output_power` publish to a `command_topic` and the
     *   firmware declares no `state_topic` for either, so Home Assistant's value
     *   is nothing but a memory of the last command *this* Home Assistant sent
     *   (the entities are `assumed_state` and read `unknown` after a restart).
     * * `switch/<dev_id>` is the same: ON wakes the unit, OFF puts it to sleep,
     *   and nothing readable comes back.
     *
     * The sensors below, by contrast, are decoded from the device's own
     * `device/state` / `system/state` payloads, so they are the honest answer to
     * "what is it doing right now". They are read-only here - just displayed.
     *
     * `pv1_power` / `pv2_power` describe the PV ports, so they are summed for the
     * production figure; the storage models that report `sys_pv_p` answer through
     * `system_pv_power` instead, and whichever of the two exists is used.
     */
    _readback() {
      const read = (key, domain = "sensor") => {
        const state = this._state(key, domain);
        if (!state) return null;
        const value = num(state.state);
        const unit = (state.attributes && state.attributes.unit_of_measurement) || "";
        const ok = state.state !== "unknown" && state.state !== "unavailable"
          && Number.isFinite(value);
        return ok ? { value, unit, text: `${value}${unit ? ` ${unit}` : ""}` } : null;
      };

      /* A word, not a number: the EMS mode entity state is `general` /
         `mqtt_ctrl` / ..., and `num()` turns that into `0`. Text states are
         therefore read raw instead of through `read()`. */
      const readText = (key, domain = "sensor") => {
        const state = this._state(key, domain);
        if (!state) return null;
        const text = String(state.state).trim();
        return text && text !== "unknown" && text !== "unavailable" ? text : null;
      };

      const pv1 = read("pv1_power");
      const pv2 = read("pv2_power");
      let pvTotal = null;
      if (pv1 || pv2) {
        // Summed here rather than read from an entity, so it has no state of its
        // own to copy - the `text` field is what `_readChip()` prints.
        const value = (pv1 ? pv1.value : 0) + (pv2 ? pv2.value : 0);
        pvTotal = { value, unit: "W", text: `${value} W` };
      } else {
        pvTotal = read("system_pv_power");
      }
      const grid = read("system_grid_power") || read("grid_on_power");
      const load = read("system_load_power") || read("system_plug_power");

      /* The mode the device itself reports. `select.*_mqtt_select` is the value
         Home Assistant last wrote (the integration keeps it retained precisely
         because the firmware has no state topic for it), so it is shown next to
         the device's own reading rather than instead of it.
         The sensor's protocol key is `ems_mode_running` but its entity is named
         "EMS Mode (Device)", so the id is matched through `_state_regex`-free
         candidate lookup: `ems_mode_device` is what the slug actually produces. */
      const deviceMode = readText("ems_mode_running") || readText("ems_mode_device");
      const selectMode = this._emsMode();

      return { pv1, pv2, pvTotal, grid, load, deviceMode, selectMode };
    }

    /** One "label: value" fragment, dropped when the device reports nothing. */
    _readChip(label, item, cls = "") {
      if (!item) return "";
      const text = typeof item === "object" && item.text ? item.text : item;
      return html`<span class="chip ${cls}"><b>${label}</b>${text}</span>`;
    }

    /**
     * Read-back of the device's real measurement, plus the honest status of the
     * two write-only controls.
     *
     * The user-facing question this answers is "did my command take effect, and
     * what is the unit doing?" - which the entity states of `power_ctrl`,
     * `output_power` and the power switch cannot answer, since none of the three
     * has a state topic. The PV / grid / load figures do come from the device,
     * so they double as proof that it is awake and producing even while the
     * switch entity says OFF.
     */
    _readbackItem() {
      const rb = this._readback();
      /* The device's own mode wins; the select is the fallback because its state
         is the integration's retained echo. Either way only the text is shown,
         so both shapes are collapsed to a string here. */
      const modeSource = rb.deviceMode || rb.selectMode;
      const modeText = modeSource
        ? String(typeof modeSource === "object" ? modeSource.text : modeSource)
        : "";
      const nothing = !rb.pvTotal && !rb.grid && !rb.load && !modeText;

      const sub = nothing
        ? this._t(
          "The device reports no measurement yet.",
          "设备尚未上报任何测量值。",
        )
        : this._t(
          "Live values decoded from the device's own state messages. "
            + "Power control and output power have no state topic, so their "
            + "boxes above hold the last value sent from this browser.",
          "以下数值来自设备自身上报的状态消息。功率控制与输出功率没有状态话题，"
            + "上方输入框会记住本机最后一次下发的值。",
        );

      return this._item({
        icon: "📊",
        name: this._t("Device read-back", "设备回读"),
        sub,
        stack: true,
        ctrl: nothing ? html`<span class="state">—</span>` : html`
          ${this._readChip(this._t("PV", "光伏"), rb.pvTotal, "pv")}
          ${this._readChip("PV1", rb.pv1)}
          ${this._readChip("PV2", rb.pv2)}
          ${this._readChip(this._t("Grid", "并网"), rb.grid, "grid")}
          ${this._readChip(this._t("Load", "负载"), rb.load, "load")}
          ${modeText
            ? html`<span class="chip mode"><b>${this._t("EMS", "EMS")}</b>${modeText}</span>`
            : ""}`,
      });
    }

    _setEmsMode(mode) {
      this._optimistic.ems_mode = mode;
      this._remember({ ems_mode: mode });
      /* Leaving mqtt_ctrl makes the lease meaningless: the firmware ignores
         `power_ctrl` in every other mode, so re-sending it would only add
         broker traffic. The switch reflects that instead of staying on while
         doing nothing. */
      if (mode !== "mqtt_ctrl" && this._timerOn) this._setTimer(false);
      this._publish(this._topic("select/<dev_id>/ems_mode/command"), mode,
        `${this._t("EMS mode", "EMS 模式")} → ${mode}`);
    }

    _emsMode() {
      const state = this._state("ems_mode", "select");
      return (state ? String(state.state) : null) || this._optimistic.ems_mode || "";
    }

    _emsOptions() {
      const options = this._attr("ems_mode", "select", "options");
      if (Array.isArray(options) && options.length) return options;
      return EMS_MODES.map((m) => m.id);
    }

    _sendPowerCtrl(opts) {
      const value = Number(this._powerCtrl);
      if (!Number.isFinite(value)) { this._showToast(this._t("Invalid value", "数值无效"), true); return; }
      /* Remembered before the send, so a failed publish still leaves the card
         showing what was attempted - that is more useful than silently going
         back to an older value the user has since replaced. */
      this._remember({ power_ctrl: value });
      /* While the beat is running it re-publishes its own value, so a plain
         send would be silently overwritten one period later - "I sent 200 W"
         then looks ignored a minute later, which is exactly the symptom this
         timer exists to cure. Retuning the beat publishes the new target
         immediately and keeps holding it, so it is the whole operation. */
      if (this._timerOn) {
        this._showToast(
          this._t(
            `Power control ${value} W (timer retuned)`,
            `功率控制 ${value} W（已同步定时下发）`,
          ),
          false,
        );
        this._keepaliveStart(value);
        return;
      }
      this._publish(this._topic("number/<dev_id>/power_ctrl/set"), String(value),
        `${this._t("Power control", "功率控制")} ${value} W`, opts);
    }

    /* ---------------------------- re-send timer ---------------------------- */

    /**
     * The period actually used, clamped into the supported window. A blank or
     * unparsable field falls back to the default rather than stopping the beat:
     * letting the lease lapse because someone cleared the input mid-edit would
     * be the worst possible outcome.
     */
    _timerPeriodValue() {
      return this._clampPeriod(this._timerPeriod);
    }

    /** `num()` maps anything unparsable to 0, so a blank field has to be caught
     * before the clamp or clearing the input would mean "every 5 s". */
    _clampPeriod(raw) {
      if (String(raw == null ? "" : raw).trim() === "") return TIMER_DEFAULT_S;
      const n = Math.round(Number(raw));
      if (!Number.isFinite(n) || n <= 0) return TIMER_DEFAULT_S;
      return Math.min(Math.max(n, TIMER_MIN_S), TIMER_MAX_S);
    }

    _timerClock(ts) {
      if (!ts) return "";
      const d = new Date(ts);
      const pad = (n) => String(n).padStart(2, "0");
      return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }

    _setTimer(on) {
      if (this._timerBusy) return;
      const want = on === true;
      /* Off must always be possible, even mid-send or when this element's
         mirror disagrees with the integration: leaving the device holding a
         power limit because the UI was out of step is far worse than a
         redundant stop call (which the service treats as a no-op). */
      if (!want) { this._keepaliveStop(); return; }
      if (this._timerOn === true) return;
      /* `power_ctrl` is only honoured in mqtt_ctrl mode, so arming the timer in
         any other mode would publish into the void. The row disables its
         buttons there; this guard covers the programmatic paths too. */
      if (this._emsMode() !== "mqtt_ctrl") return;
      const value = Number(this._powerCtrl);
      if (!Number.isFinite(value)) {
        this._showToast(this._t("Invalid value", "数值无效"), true);
        return;
      }
      this._keepaliveStart(value);
    }

    /**
     * Start (or retune) the server-side beat.
     *
     * The value is sent by the integration, so the card does not re-publish it
     * here - a second publish would only duplicate the first beat.
     */
    async _keepaliveStart(power) {
      this._timerBusy = true;
      this.requestUpdate();
      try {
        await this._hass.callService("hoymiles_g2", "start_power_ctrl_keepalive", {
          dev_id: this._dev(),
          power,
          period: this._timerPeriodValue(),
        });
        // The state topic carries the authoritative count, so read it back
        // instead of assuming the call did what was asked.
        this._syncKeepalive();
      } catch (err) {
        this._showToast(this._t(
          `Could not start the timer: ${err.message || err}`,
          `无法开启定时下发：${err.message || err}`,
        ), true);
      } finally {
        this._timerBusy = false;
        this.requestUpdate();
      }
    }

    async _keepaliveStop() {
      this._timerBusy = true;
      this.requestUpdate();
      try {
        await this._hass.callService("hoymiles_g2", "stop_power_ctrl_keepalive", {
          dev_id: this._dev(),
        });
        this._syncKeepalive();
      } catch (err) {
        this._showToast(this._t(
          `Could not stop the timer: ${err.message || err}`,
          `无法关闭定时下发：${err.message || err}`,
        ), true);
      } finally {
        this._timerBusy = false;
        this.requestUpdate();
      }
    }

    /**
     * Read the integration's running state from its entity.
     *
     * The keep-alive publishes a retained topic, but a card must not depend on
     * having received it - right after a page load the retained message may not
     * have arrived yet. The integration mirrors the same payload into an
     * entity's attributes, which `hass.states` always has, so the row is
     * correct the moment it renders.
     */
    _syncKeepalive() {
      const state = this._state("power_ctrl_keepalive", "sensor");
      this._applyKeepalive(state ? state.attributes : null);
    }

    /**
     * Mirror the integration's state onto the row.
     *
     * `set hass` runs for every state change in the whole system, so the
     * re-render is skipped unless something actually differs - otherwise the
     * card would redraw continuously for no reason.
     */
    _applyKeepalive(payload) {
      if (!payload || typeof payload !== "object") return;
      const on = payload.enabled === true;
      /* The sensor always reports the period of the *last* beat, even when no
         beat is running - and an idle sensor answers with the built-in default,
         which would silently undo a period the user had chosen earlier. The
         stored period is only authoritative while a beat is actually running. */
      const period = on && payload.period != null
        ? String(this._clampPeriod(payload.period))
        : this._timerPeriod;
      const count = typeof payload.count === "number" ? payload.count : 0;
      const lastAt = typeof payload.last_at === "number" ? payload.last_at : 0;
      const power = typeof payload.power === "number" ? payload.power : NaN;
      /* An error is only worth showing while stopped: a beat that is running
         has already recovered by definition, and a stale message would sit
         there contradicting the "re-sending every N s" line right above it. */
      const error = !on && payload.error ? String(payload.error) : "";
      if (on === this._timerOn && period === this._timerPeriod
        && count === this._timerCount && lastAt === this._timerLastAt
        && error === this._timerError && power === this._timerPower) {
        return;
      }
      const previousPower = this._timerPower;
      const powerMoved = Number.isFinite(power) && power !== previousPower;
      this._timerOn = on;
      this._timerPeriod = period;
      this._timerCount = count;
      this._timerLastAt = lastAt;
      this._timerError = error;
      this._timerPower = power;
      /* A running beat holds a specific wattage in the integration, which is
         server-side truth and therefore outranks whatever this browser
         remembered. Mirror it into the slider so a page opened while 200 W is
         being held shows 200 W - the value the user "sent" in the first place.

         Only on a *transition* of the held power, and only when the slider
         still shows the old held value: applying it on every push would fight
         the user, snapping a drag back before they could press 下发. */
      if (on && powerMoved) {
        const untouched = this._powerCtrl === "" || Number.isNaN(previousPower)
          || num(this._powerCtrl) === power || num(this._powerCtrl) === previousPower;
        if (untouched) this._powerCtrl = String(power);
        /* Persist the server's value too: it is what the device is actually
           holding, so it is the best thing to restore on the next visit. */
        this._remember({ power_ctrl: power, timer_period: this._clampPeriod(period) });
      }
      this.requestUpdate();
    }

    /** Turn a keep-alive error into a sentence the user can act on.
     *
     * The integration reports English diagnostics meant for the log. Two of them
     * have a real user-facing meaning, and one is actively misleading without
     * context: the EMS select can read `mqtt_ctrl` while the device is actually
     * in another mode, because the select's state topic is a retained value the
     * firmware only refreshes every few minutes. Saying just "not mqtt_ctrl"
     * next to a row that visibly *does* say mqtt_ctrl looks like a bug.
     */
    _timerErrorText(err) {
      const text = String(err || "");
      const ems = text.match(/EMS mode is (\w+), not (\w+)/i);
      if (ems) {
        return this._t(
          `The device reports ${ems[1]}, so it ignores power control - the EMS mode shown above may be stale. `
            + `Switch to ${ems[2]} and try again.`,
          `设备实际处于 ${ems[1]}，会忽略功率控制（上方的 EMS 模式显示可能是旧值）。`
            + `请切到 ${ems[2]} 后重试。`,
        );
      }
      if (/integration unloaded/i.test(text)) {
        return this._t("The integration was reloaded - turn this on again.",
          "集成已重新加载，请重新开启。");
      }
      return text;
    }

    async _setTimerPeriod(raw, input) {
      const clamped = this._clampPeriod(raw);
      this._timerPeriod = String(clamped);
      /* The period is part of the remembered set even while the beat is off: the
         user picks 15 s once and expects to find it next time, not to retype it
         before every start. */
      this._remember({ timer_period: clamped });
      /* Write the clamped value back to the field by hand.
       *
       * Lit only rewrites a bound property when the *previous committed value*
       * differs, so typing 120 into a field already holding 60 leaves "120" on
       * screen after the clamp - the value silently became 60 while the box
       * kept showing the rejected number. Overwriting here is what makes the
       * 60 s ceiling visible instead of merely effective. */
      if (input && String(input.value) !== String(clamped)) {
        input.value = String(clamped);
      }
      this.requestUpdate();
      /* A new period must reach the integration, not just this element: the
         beat is scheduled server side. Restarting retunes it so the change
         takes effect immediately.

         The power comes from what the beat is already holding, not from the
         slider: the slider may show an unsent value, and editing the period
         must not silently push that value onto the device. */
      if (!this._timerOn) return;
      if (!Number.isFinite(this._timerPower)) return;
      await this._keepaliveStart(this._timerPower);
    }

    _sendOutputPower() {
      const value = Number(this._outputPower);
      if (!Number.isFinite(value)) { this._showToast(this._t("Invalid value", "数值无效"), true); return; }
      this._remember({ output_power: value });
      this._publish(this._topic("number/<dev_id>/output_power/set"), String(value),
        `${this._t("Output power", "输出功率")} ${value} W`);
    }

    _sendPhase() {
      const payload = {
        phase_a: Number(this._phase.a),
        phase_b: Number(this._phase.b),
        phase_c: Number(this._phase.c),
      };
      if (!Object.values(payload).every(Number.isFinite)) {
        this._showToast(this._t("Invalid value", "数值无效"), true);
        return;
      }
      this._remember({ phase: { a: payload.phase_a, b: payload.phase_b, c: payload.phase_c } });
      this._publish(this._topic("number/<dev_id>/phase_output_power/set"), payload,
        `${this._t("Phase output", "多相输出")} ${payload.phase_a}/${payload.phase_b}/${payload.phase_c} W`);
    }

    _sendTouGet() {
      this._publish(this._topic("sensor/<dev_id>/tou_plan/get"), { week: this._week },
        `${this._t("Get TOU plan", "获取 TOU 计划")} ${this._week}`);
    }

    _reboot() {
      const ok = window.confirm(this._t(
        "Reboot the device now?", "确认立即重启设备？",
      ));
      if (!ok) return;
      this._publish(this._topic("button/<dev_id>/reboot/trigger"), "RESTART",
        this._t("Reboot", "重启"));
    }

    /* ------------------------------- log ------------------------------- */

    /** The two wildcards that cover this device: its tree, and ours. */
    _logTopics() {
      return [this._topic("+/<dev_id>/#"), `hoymiles_g2/${this._dev()}/#`];
    }

    /**
     * Which way does a message go? Home Assistant writes to the command side of
     * a topic (`/set`, `/command`, `/trigger`, `/get`); everything else on the
     * device's tree is published by the device itself. The `hoymiles_g2/` family
     * belongs to the integration, which is also this end of the link.
     */
    _logDown(topic) {
      if (String(topic).startsWith("hoymiles_g2/")) return true;
      return LOG_DOWNLINK.test(String(topic));
    }

    /**
     * The topic of one message, split so the device id can be dimmed: every
     * line carries it, and it is the least interesting part. The three pieces
     * are spans, not one string, but their text adds up to the topic exactly as
     * it goes over the wire, so selecting a row still copies the real thing.
     *
     * The full path is shown on purpose: `sensor/quick/state` is shorter, but it
     * is not the topic - the user has to be able to read (and copy) what was
     * actually published.
     */
    _logTopic(topic, host) {
      const dev = this._dev();
      const at = String(topic).indexOf(`/${dev}/`);
      if (at < 0) {
        host.textContent = String(topic);
        return;
      }
      const before = document.createElement("span");
      before.textContent = String(topic).slice(0, at + 1);
      const id = document.createElement("span");
      id.className = "log-dev";
      id.textContent = dev;
      const after = document.createElement("span");
      after.textContent = String(topic).slice(at + 1 + dev.length);
      host.append(before, id, after);
    }

    /**
     * The payload, on a single wrapped line when it is JSON, and capped.
     *
     * It used to be pretty printed, but that turned a `quick/state` (once a
     * second) into a sixty line block, and every long payload then needed its
     * own scrollbar inside the list's scrollbar. Compact keeps a row readable,
     * keeps the list the only thing that scrolls, and still shows every value -
     * the user asked for exactly that ("one scrollbar is enough").
     */
    _logPayload(payload) {
      const text = String(payload == null ? "" : payload);
      if (text.trim() === "") return this._t("(empty)", "（空）");
      let out = text;
      const trimmed = text.trim();
      if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
        try {
          out = JSON.stringify(JSON.parse(text));
        } catch (err) {
          out = text; // not valid JSON after all - show it raw
        }
      }
      if (out.length > LOG_PAYLOAD_MAX) {
        const rest = out.length - LOG_PAYLOAD_MAX;
        return `${out.slice(0, LOG_PAYLOAD_MAX)}… ${this._t(
          `(${rest} more characters)`, `（还有 ${rest} 个字符）`,
        )}`;
      }
      return out;
    }

    /** One entry, ready for the list. */
    _logEntry(msg) {
      const topic = String((msg && msg.topic) || "");
      const payload = (msg && msg.payload) != null ? String(msg.payload) : "";
      const down = this._logDown(topic);
      const now = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      return {
        topic,
        down,
        text: this._logPayload(payload),
        clock: `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`,
      };
    }

    /**
     * One rendered row. Built with DOM calls and `textContent` rather than
     * markup: a payload is arbitrary text from the broker, and this way there is
     * nothing to escape.
     */
    _logRow(entry) {
      const row = document.createElement("div");
      row.className = `log-row ${entry.down ? "down" : "up"}`;

      const meta = document.createElement("div");
      meta.className = "log-meta";
      const time = document.createElement("span");
      time.className = "log-time";
      time.textContent = entry.clock;
      const dir = document.createElement("span");
      dir.className = "log-dir";
      dir.textContent = entry.down
        ? this._t("HA → device", "HA 下发")
        : this._t("device → HA", "设备上报");
      const topic = document.createElement("span");
      topic.className = "log-topic";
      this._logTopic(entry.topic, topic);
      topic.title = entry.topic;
      meta.append(time, dir, topic);

      const body = document.createElement("pre");
      body.className = "log-payload";
      body.textContent = entry.text;

      row.append(meta, body);
      return row;
    }

    _onLogMessage(msg) {
      if (!this._logOpen || !msg) return;
      const entry = this._logEntry(msg);
      this._log.push(entry);
      while (this._log.length > LOG_MAX) {
        this._log.shift();
        this._logDropped += 1;
      }
      this._appendLogRow(entry);
    }

    /**
     * Append one row, keeping the list bounded and scrolled to the newest
     * message - unless the user has scrolled up to read, in which case the view
     * is left where it is.
     */
    _appendLogRow(entry) {
      const list = this._logList;
      if (!list) return; // the panel is not in the DOM yet; the buffer has it
      const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 24;
      list.appendChild(this._logRow(entry));
      while (list.children.length > LOG_MAX) list.removeChild(list.firstChild);
      if (atBottom) list.scrollTop = list.scrollHeight;
      this._syncLogFoot();
    }

    /**
     * Pick up the freshly rendered panel (or restore it after a re-render) and
     * refill it from the buffer.
     *
     * The list is filled by hand and deliberately not by Lit: the device pushes
     * once a second, and re-rendering the card - sliders, segments and all -
     * for every message would be a lot of churn for a log. Lit leaves the
     * children of an element it did not create alone, so the rows survive.
     */
    _syncLogDom() {
      const root = this.renderRoot;
      const list = root && root.querySelector ? root.querySelector(".log-list") : null;
      if (!list) {
        this._logList = null;
        return;
      }
      if (list !== this._logList) {
        this._logList = list;
        list.textContent = "";
        for (const entry of this._log) list.appendChild(this._logRow(entry));
        list.scrollTop = list.scrollHeight;
      }
      this._syncLogFoot();
    }

    /** The counter and the hint line, which also live outside Lit. */
    _syncLogFoot() {
      const root = this.renderRoot;
      if (!root || !root.querySelector) return;
      const open = this._config && this._config.show_log !== false;
      const count = root.querySelector(".log-count");
      if (count) {
        const dropped = this._logDropped
          ? this._t(` · ${this._logDropped} dropped`, ` · 已丢弃较早的 ${this._logDropped} 条`)
          : "";
        count.textContent = this._logErr
          ? ""
          : this._t(`${this._log.length} messages`, `${this._log.length} 条`) + dropped;
      }
      const hint = root.querySelector(".log-hint");
      if (hint) {
        hint.textContent = this._logErr
          ? this._logErr
          : (this._log.length || !open
            ? ""
            : this._t("Waiting for MQTT traffic…", "等待 MQTT 数据…"));
        hint.className = `log-hint ${this._logErr ? "err" : ""}`;
      }
    }

    /** Turn a subscribe failure into something a user can act on. */
    _logSubscribeError(err) {
      const raw = String((err && err.message) || err || "");
      if (/unauthor|admin|forbidden|401|403/i.test(raw)) {
        return this._t(
          "Subscribing to MQTT needs an administrator account "
          + "(Home Assistant restricts mqtt/subscribe).",
          "订阅 MQTT 需要管理员账号（Home Assistant 限制 mqtt/subscribe 命令）。",
        );
      }
      if (/unknown command|unknown_command|not found|not_found/i.test(raw)) {
        return this._t(
          "This Home Assistant has no mqtt/subscribe command - is the MQTT integration set up?",
          "当前 Home Assistant 没有 mqtt/subscribe 命令——MQTT 集成是否已配置？",
        );
      }
      return `${this._t("Subscribe failed", "订阅失败")}: ${raw}`;
    }

    /**
     * Subscribe to the device's topics.
     *
     * `_logGen` guards the await: a subscription that lands after the switch was
     * turned off again (or the card moved to another device) must be dropped
     * instead of being stashed as a live one, or the list would keep growing
     * with messages nobody asked for.
     */
    async _subscribeLog() {
      this._logErr = "";
      this._syncLogFoot();
      const connection = this._hass && this._hass.connection;
      if (!connection || typeof connection.subscribeMessage !== "function") {
        this._logErr = this._t(
          "No Home Assistant websocket connection.",
          "没有 Home Assistant 的 WebSocket 连接。",
        );
        this._syncLogFoot();
        this.requestUpdate();
        return;
      }

      const gen = (this._logGen += 1);
      for (const topic of this._logTopics()) {
        try {
          const unsub = await connection.subscribeMessage(
            (msg) => this._onLogMessage(msg),
            { type: "mqtt/subscribe", topic, qos: LOG_QOS },
          );
          if (gen !== this._logGen) {
            if (typeof unsub === "function") unsub();
            continue;
          }
          if (typeof unsub === "function") this._logUnsubs.push(unsub);
        } catch (err) {
          if (gen !== this._logGen) break;
          this._logErr = this._logSubscribeError(err);
        }
      }
      this._syncLogFoot();
      this.requestUpdate();
    }

    _unsubscribeLog() {
      const subs = this._logUnsubs;
      this._logUnsubs = [];
      this._logGen += 1; // any in-flight subscribe is now stale
      for (const unsub of subs) {
        try {
          const result = unsub();
          if (result && typeof result.catch === "function") result.catch(() => {});
        } catch (err) {
          /* already gone - nothing to do */
        }
      }
    }

    _toggleLog(on) {
      if (on) {
        this._logOpen = true;
        this._log = [];
        this._logDropped = 0;
        this._logList = null;
        this.requestUpdate();
        this._subscribeLog();
      } else {
        this._closeLog();
      }
    }

    _closeLog() {
      this._logOpen = false;
      this._unsubscribeLog();
      /* Start clean next time: the retained configs and the last states arrive
         again on the next subscribe anyway, so keeping them would only show the
         same messages twice. */
      this._log = [];
      this._logDropped = 0;
      this._logErr = "";
      this._logList = null;
      this.requestUpdate();
    }

    _clearLog() {
      this._log = [];
      this._logDropped = 0;
      if (this._logList) this._logList.textContent = "";
      this._syncLogFoot();
    }

    /* ----------------------------- rendering ----------------------------- */

    render() {
      if (!this._config) return html``;
      // A missing entity means the device does not implement that feature, so
      // the row is dropped rather than shown as a control that does nothing.
      // The explicit `show_*` config still wins, for users who want it back.
      const showPhase = this._config.show_phase !== undefined
        ? this._config.show_phase !== false
        : this._hasEntity("phase_a_output_power", "number");
      const showPowerCtrl = this._config.show_power_ctrl !== false;
      const showTou = this._hasEntity("tou_plan_status", "sensor");
      const showLog = this._config.show_log !== false;

      return html`
        <ha-card>
          <div class="head">
            <div class="title">${this._text(this._config.title) || this._t("Control", "控制")}</div>
            ${this._config.subtitle === false ? "" : html`
              <div class="sub">${this._t(
                "Commands are sent straight to the device",
                "指令直接下发到设备",
              )}</div>`}
          </div>
          ${this._group(this._t("Power & mode", "电源与模式"), [
            this._switchItem(),
            this._readbackItem(),
            this._emsItem(),
          ])}
          ${this._group(this._t("Power settings", "功率设置"), [
            showPowerCtrl ? this._powerCtrlItem() : "",
            showPowerCtrl ? this._timerItem() : "",
            this._outputItem(),
            showPhase ? this._phaseItem() : "",
          ])}
          ${this._group(this._t("Plan & maintenance", "计划与维护"), [
            showTou ? this._touItem() : "",
            this._rebootItem(),
            showLog ? html`${this._logItem()}${this._logOpen ? this._logPanel() : ""}` : "",
          ])}
          ${this._toast === "" ? "" : html`
            <div class="toast ${this._toastError ? "err" : ""}">${this._toast}</div>`}
        </ha-card>
      `;
    }

    /** One grouped block, like an iOS settings section. */
    _group(title, items) {
      return html`
        <div class="group-wrapper">
          ${title ? html`<div class="group-title">${title}</div>` : ""}
          <div class="group">${items}</div>
        </div>`;
    }

    /**
     * One settings row: icon, name (with an optional grey sub-line), and the
     * control right-aligned. `stack` puts the control on its own line, which is
     * what the three-phase inputs need.
     */
    _item({ icon, name, sub, subClass, topic, ctrl, stack }) {
      const showTopics = this._config.show_topics === true;
      return html`
        <div class="item ${stack ? "stack" : ""}">
          ${icon ? html`<span class="ico">${icon}</span>` : ""}
          <div class="nm">${name}
            ${sub ? html`<small class=${subClass || ""}>${sub}</small>` : ""}
            ${showTopics && topic ? html`<small><code>${topic}</code></small>` : ""}
          </div>
          <div class="ctrl">${ctrl}</div>
        </div>`;
    }

    /** iOS segmented control. `options` = [{id, label, enabled, title, pending}] */
    _segment(options, current, onPick, extraClass = "") {
      return html`
        <div class="seg ${extraClass}">
          ${options.map((opt) => html`
            <button class=${[
              opt.id === current ? "on" : "",
              opt.pending ? "pending" : "",
            ].filter(Boolean).join(" ")}
              ?disabled=${opt.enabled === false}
              title=${opt.title || ""}
              @click=${() => onPick(opt.id)}>${opt.label}</button>`)}
        </div>`;
    }

    /**
     * iOS slider row: track on the left, editable read-out on the right.
     *
     * The track keeps `--pct` in sync with the value so the tinted fill follows
     * the knob without a second element. Dragging only updates the draft value;
     * nothing is published until the send button is pressed (the power values
     * have to be re-sent every minute, so publishing on every input event would
     * flood the broker).
     *
     * Both inputs stay inside `[lo, hi]`. The draft value may legitimately sit
     * outside the range for a moment - `_seedInputs` reads a live entity whose
     * bounds the firmware rewrites underneath us - and letting it through would
     * put a number in the read-out that the slider cannot represent and that a
     * press of the send button would publish as-is.
     */
    _slider({ value, min, max, step, unit, tag, disabled, onInput, onSend, sendLabel }) {
      const lo = num(min);
      const hi = num(max);
      const current = num(value);
      const inRange = Number.isFinite(current)
        ? Math.min(Math.max(current, lo), hi)
        : lo;
      const span = hi - lo;
      const pct = span > 0 ? ((inRange - lo) / span) * 100 : 0;

      return html`
        <div class="slider">
          ${tag ? html`<span class="tag">${tag}</span>` : ""}
          <input type="range" min=${lo} max=${hi} step=${step}
            .value=${String(inRange)} ?disabled=${disabled}
            style="--pct:${pct.toFixed(1)}%"
            @input=${(e) => onInput(e.target.value)} />
          <input type="number" min=${lo} max=${hi} step=${step}
            .value=${String(Number.isFinite(current) ? current : "")}
            ?disabled=${disabled}
            @input=${(e) => onInput(e.target.value)}
            @change=${(e) => {
              // Typing is free-form; leaving the field is not. Snap a value the
              // entity cannot hold back into range so the read-out, the track
              // and the value that gets published never disagree. The DOM value
              // is rewritten here as well - the draft alone would not show until
              // the next `hass` push, i.e. up to a second later.
              const typed = num(e.target.value);
              const fixed = Number.isFinite(typed)
                ? Math.min(Math.max(typed, lo), hi)
                : inRange;
              if (fixed !== typed) {
                e.target.value = String(fixed);
                onInput(String(fixed));
              }
            }} />
          <span class="unit">${unit}</span>
          ${onSend ? html`
            <button class="btn primary" ?disabled=${disabled}
              @click=${onSend}>${sendLabel}</button>` : ""}
        </div>`;
    }

    /** Slider bounds for a numeric entity, with the protocol defaults. */
    _bounds(key, fallbackLo, fallbackHi) {
      const rawLo = this._attr(key, "number", "min");
      const rawHi = this._attr(key, "number", "max");
      const lo = rawLo != null ? num(rawLo) : fallbackLo;
      const hi = rawHi != null ? num(rawHi) : fallbackHi;
      // A degenerate range would divide by zero in the fill calculation.
      return hi > lo ? { lo, hi } : { lo: fallbackLo, hi: fallbackHi };
    }

    /** Step for a numeric entity, falling back to the protocol default.
     *
     * `step` is part of the entity's own declaration and a wrong value is not
     * harmless: a slider whose step is finer than the device accepts sends
     * values it rejects, and one that is coarser makes fine control impossible.
     */
    _step(key, fallback) {
      const raw = this._attr(key, "number", "step");
      const step = raw != null ? num(raw) : NaN;
      return Number.isFinite(step) && step > 0 ? step : fallback;
    }

    /** Keep a value inside a range (invalid input falls back to the low bound). */
    _clamp(value, lo, hi) {
      const v = num(value);
      if (!Number.isFinite(v)) return lo;
      return Math.min(Math.max(v, lo), hi);
    }

    _switchItem() {
      const view = this._switchView();
      /* The sub-line is where the feedback lands: the button already flips the
         instant it is pressed, and this explains the wait / confirms it.

         An optimistic switch is a different story. The firmware publishes no
         readable ON/OFF (its discovery state topic is a nested JSON document),
         so Home Assistant only remembers the last command *it* sent - which is
         why the row said "已休眠" on a device that was plainly producing. Saying
         "last commanded" instead of claiming a device state is the honest
         wording, and the power read-out row below is what actually shows the
         device is alive. */
      const sub = view.pending
        ? this._t(
          `Powering ${view.pending === "on" ? "up" : "down"}…`,
          `${view.pending === "on" ? "正在开机" : "正在关机"}…`,
        )
        : view.optimistic
          ? (view.commanded
            ? this._t(
              `Last command: ${view.on ? "on" : "off"} (the device does not report its switch state)`,
              `上次下发：${view.on ? "开机" : "关机"}（设备不上报开关状态）`,
            )
            : this._t(
              "No command sent yet - the device does not report its switch state. See the power read-out below.",
              "尚未下发指令——设备不上报开关状态，请看下方的实时回读。",
            ))
          : view.confirmed
            ? this._t(
              view.on ? "Powered on ✓" : "Powered off ✓",
              view.on ? "已开机 ✓" : "已关机 ✓",
            )
            : view.on
              ? this._t("running", "运行中")
              : this._t("standby", "已休眠");
      const subClass = view.pending ? "busy" : view.confirmed ? "done" : "";
      return this._item({
        icon: "⚡",
        name: this._t("Power", "设备开关"),
        sub,
        subClass,
        topic: this._topic("switch/<dev_id>/set"),
        ctrl: this._segment(
          [
            { id: "on", label: this._t("On", "开机"),
              pending: view.pending === "on" },
            { id: "off", label: this._t("Off", "关机"),
              pending: view.pending === "off" },
          ],
          view.on ? "on" : "off",
          (id) => this._setSwitch(id === "on"),
        ),
      });
    }

    _emsItem() {
      const current = this._emsMode();
      const supported = this._emsOptions();
      const options = EMS_MODES.map((mode) => ({
        id: mode.id,
        label: this._t(mode.en, mode.zh),
        enabled: supported.includes(mode.id),
        title: supported.includes(mode.id)
          ? mode.id
          : this._t(
            "This mode is not offered by the device's firmware.",
            "该设备固件未提供此模式。",
          ),
      }));
      return this._item({
        icon: "🔋",
        name: this._t("EMS mode", "EMS 模式"),
        sub: current === "" ? "—" : current,
        topic: this._topic("select/<dev_id>/ems_mode/command"),
        ctrl: this._segment(options, current, (id) => this._setEmsMode(id)),
      });
    }

    /** Range the power-control slider offers, and the cap the device reports.
     *
     * Two different numbers are in play and they must not be confused:
     *
     * * The **rated** maximum - `output_power`'s declared `max` (800 W on a
     *   micro inverter). This is the physical capability and it never moves.
     * * The **effective** cap - the value of `power_ctrl`'s declared `max`.
     *   The firmware rewrites that payload after every `output_power` command
     *   so it always equals the last `output_power` the device accepted, i.e.
     *   the wattage the hardware will not exceed right now.
     *
     * The slider used to stop at the effective cap, which made the control look
     * broken: a device capped at 132 W could not be told to produce 300 W even
     * though the firmware accepts it (measured: publishing 700 while the
     * declared `max` was 234 was honoured and the device output 715 W). So the
     * slider now spans the rated maximum, and the effective cap is surfaced as
     * a hint instead of a hard stop.
     *
     * The effective cap is read from the *declared attribute*, never from the
     * `output_power` entity's state: that entity has no state topic, so its
     * value is only whatever Home Assistant last commanded and goes stale
     * immediately. The discovery payload, by contrast, comes from the device.
     */
    _powerRange(declaredLo, declaredHi) {
      const rated = this._attr("output_power", "number", "max");
      const hi = Number.isFinite(num(rated)) && num(rated) > declaredLo
        ? num(rated)
        : declaredHi;
      return { lo: declaredLo, hi, cap: declaredHi };
    }

    _powerCtrlItem() {
      const ready = this._emsMode() === "mqtt_ctrl";
      const declared = this._bounds("power_ctrl", -1000, 1000);
      const { lo, hi, cap } = this._powerRange(declared.lo, declared.hi);
      // The firmware declares the granularity itself and it differs per model
      // (0.1 W on a storage unit, 1 W on a micro inverter), so the slider must
      // follow the entity rather than assume the finer one.
      const step = this._step("power_ctrl", 0.1);
      const sub = !ready
        ? this._t("switch EMS to mqtt_ctrl first", "需先切到 mqtt_ctrl")
        : cap < hi
          // The device will refuse to exceed `cap` whatever is sent, so say so
          // rather than let a large value look like it had no effect.
          ? this._t(
            `${lo} ~ ${hi} W; device capped at ${cap} W by output power`,
            `${lo} ~ ${hi} W；设备当前受输出功率限制为 ${cap} W`,
          )
          : this._t(
            `${lo} ~ ${hi} W, re-send at least once a minute`,
            `${lo} ~ ${hi} W，需至少每分钟下发一次`,
          );
      return this._item({
        icon: "🎛",
        name: this._t("Power control", "功率控制"),
        sub,
        topic: this._topic("number/<dev_id>/power_ctrl/set"),
        stack: true,
        ctrl: this._slider({
          value: this._powerCtrl,
          min: lo,
          max: hi,
          step,
          unit: "W",
          disabled: !ready,
          sendLabel: this._t("Send", "下发"),
          onInput: (v) => { this._powerCtrl = v; },
          onSend: () => this._sendPowerCtrl(),
        }),
      });
    }

    /**
     * The re-send timer, directly under the slider it applies to.
     *
     * `power_ctrl` is a lease that the firmware drops after about a minute (it
     * falls back to `output_power`), which is why a single send looks like the
     * device "ignores" the value after a short while. Re-publishing on a period
     * holds it; this row is the switch for that.
     *
     * The beat is run by the integration, not by this element. An earlier
     * version used a browser `setTimeout`, which fired once and then died the
     * moment the dashboard was left - navigation, reload, or closing the tab
     * cleared it, and the device reverted a minute later with no visible cause.
     * Living in Home Assistant means the value is held whether or not any
     * dashboard is open, and this row is only a remote control for it - which
     * is why it reads its state back from the entity instead of trusting a
     * local flag.
     */
    _timerItem() {
      const ready = this._emsMode() === "mqtt_ctrl";
      const on = this._timerOn === true && ready;
      const period = this._timerPeriodValue();
      const sub = !ready
        ? this._t("Switch EMS to mqtt_ctrl first", "需先切到 mqtt_ctrl")
        : this._timerError
          ? this._timerErrorText(this._timerError)
          : on
            ? this._t(
              `Re-sending every ${period} s · ${this._timerCount} sent`
                + (this._timerLastAt ? ` · last ${this._timerClock(this._timerLastAt)}` : ""),
              `每 ${period} 秒下发一次 · 已下发 ${this._timerCount} 次`
                + (this._timerLastAt ? ` · 上次 ${this._timerClock(this._timerLastAt)}` : ""),
            )
            : this._t(
              `Off. The device drops power control after ~${TIMER_LEASE_S} s - `
                + "turn this on and Home Assistant keeps sending it, even with no dashboard open.",
              `已关闭。设备约 ${TIMER_LEASE_S} 秒后自动失效——`
                + "打开后由 Home Assistant 持续下发，关闭页面也不受影响。",
            );
      return this._item({
        icon: "⏱",
        name: this._t("Re-send timer", "定时下发"),
        sub,
        subClass: on ? "ticking" : "",
        /* The row is stacked for the same reason the two sliders are: the
           segment plus the number box plus the unit do not fit beside the name
           at every width. Unstacked they wrapped onto a second line, the row
           grew taller than `.item` allows and `.group { overflow: hidden }`
           clipped the sub-line away entirely - which is why turning the timer
           on showed nothing but the word 定时下发. */
        stack: true,
        ctrl: html`
          ${this._segment(
            [
              { id: "on", label: this._t("On", "开启"), enabled: ready && !this._timerBusy },
              { id: "off", label: this._t("Off", "关闭"), enabled: ready && !this._timerBusy },
            ],
            on ? "on" : "off",
            (id) => this._setTimer(id === "on"),
          )}
          <input type="number" class="narrow" min=${TIMER_MIN_S} max=${TIMER_MAX_S}
            step="1" .value=${String(period)} ?disabled=${!ready || this._timerBusy}
            @change=${(e) => this._setTimerPeriod(e.target.value, e.target)} />
          <span class="state">${this._t("s", "秒")}</span>`,
      });
    }

    _outputItem() {
      const { lo, hi } = this._bounds("output_power", 100, 2000);
      return this._item({
        icon: "📤",
        name: this._t("Output power", "输出功率"),
        sub: this._t(`Range ${lo} ~ ${hi} W.`, `范围 ${lo} ~ ${hi} W。`),
        topic: this._topic("number/<dev_id>/output_power/set"),
        stack: true,
        ctrl: this._slider({
          value: this._outputPower,
          min: lo,
          max: hi,
          step: 1,
          unit: "W",
          sendLabel: this._t("Send", "下发"),
          onInput: (v) => { this._outputPower = v; },
          onSend: () => this._sendOutputPower(),
        }),
      });
    }

    _phaseItem() {
      const { lo, hi } = this._bounds("phase_a_output_power", 100, 2500);
      const row = (key, label) => this._slider({
        tag: label,
        value: this._phase[key],
        min: lo,
        max: hi,
        step: 1,
        unit: "W",
        onInput: (v) => { this._phase = { ...this._phase, [key]: v }; },
      });
      return this._item({
        icon: "🔌",
        name: this._t("Phase output", "多相输出功率"),
        sub: this._t(
          `Range ${lo} ~ ${hi} W, sent as {phase_a, phase_b, phase_c}.`,
          `范围 ${lo} ~ ${hi} W，按 {phase_a, phase_b, phase_c} 下发。`,
        ),
        topic: this._topic("number/<dev_id>/phase_output_power/set"),
        stack: true,
        ctrl: html`
          ${row("a", "A")}${row("b", "B")}${row("c", "C")}
          <div class="slider end">
            <button class="btn primary"
              @click=${() => this._sendPhase()}>${this._t("Send", "下发")}</button>
          </div>`,
      });
    }

    _touItem() {
      const options = WEEKDAYS.map((d) =>
        `<option value="${d}" ${d === this._week ? "selected" : ""}>${d}</option>`).join("");
      return this._item({
        icon: "📅",
        name: this._t("Get TOU plan", "获取 TOU 计划"),
        sub: this._t(
          "Reply arrives on tou_plan/status; edited below",
          "应答发布在 tou_plan/status；编辑见下方",
        ),
        topic: this._topic("sensor/<dev_id>/tou_plan/get"),
        ctrl: html`
          <select @change=${(e) => { this._week = e.target.value; }}>
            ${this._untrusted(options)}
          </select>
          <button class="btn"
            @click=${() => this._sendTouGet()}>${this._t("Get", "获取")}</button>`,
      });
    }

    _rebootItem() {
      return this._item({
        icon: "🔄",
        name: this._t("Reboot", "重启设备"),
        sub: this._t("Takes about a minute", "约需一分钟"),
        topic: this._topic("button/<dev_id>/reboot/trigger"),
        ctrl: html`
          <button class="btn danger"
            @click=${() => this._reboot()}>${this._t("Reboot", "重启")}</button>`,
      });
    }

    /**
     * The MQTT log switch. Off by default: nothing is subscribed - and nothing
     * is shown - until it is turned on, so the card costs nothing in normal use.
     */
    _logItem() {
      const open = this._logOpen === true;
      return this._item({
        icon: "📋",
        name: this._t("MQTT log", "MQTT 日志"),
        sub: open
          ? this._t(
            "Live traffic: what the device reports and what HA sends",
            "实时数据：设备上报 + HA 下发",
          )
          : this._t(
            "Off. Turn on to watch what the device reports and what Home Assistant sends",
            "默认关闭。打开后显示设备上报与 HA 下发的数据",
          ),
        ctrl: html`
          <ha-switch .checked=${open}
            @change=${(e) => this._toggleLog(e.target.checked)}></ha-switch>`,
      });
    }

    /**
     * The panel: a toolbar (counter + clear) and an empty list. Rows are added
     * by `_syncLogDom` / `_appendLogRow`, not by Lit - see `_syncLogDom`.
     */
    _logPanel() {
      return html`
        <div class="log-block">
          <div class="log-head">
            <span class="log-title">${this._t("Traffic", "通信记录")}</span>
            <span class="log-count"></span>
            <button class="btn small"
              @click=${() => this._clearLog()}>${this._t("Clear", "清空")}</button>
          </div>
          <div class="log-list"></div>
          <div class="log-hint"></div>
        </div>`;
    }

    _untrusted(markup) {
      const template = document.createElement("template");
      template.innerHTML = markup;
      return template.content.cloneNode(true);
    }
  }

  /* ------------------------------------------------------------------ *
   * Visual editor
   * ------------------------------------------------------------------ */
  class HoymilesControlEditor extends LitElement {
    static get properties() {
      return { _config: { type: Object }, hass: { type: Object } };
    }

    setConfig(config) {
      this._config = { ...(config || {}) };
    }

    _changed(field) {
      return (event) => {
        const config = { ...(this._config || {}), [field]: event.target.value };
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config } }));
      };
    }

    _toggle(field) {
      return (event) => {
        const config = { ...(this._config || {}), [field]: event.target.checked };
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config } }));
      };
    }

    static get styles() {
      return css`
        .row { padding: 8px; }
        ha-textfield { display: block; width: 100%; margin-bottom: 8px; }
        .sw { display: flex; align-items: center; gap: 10px; padding: 6px 0;
              font-size: 14px; color: var(--primary-text-color); }
      `;
    }

    render() {
      const config = this._config || {};
      return html`
        <div class="row">
          <ha-textfield label="dev_id (required)" .value=${config.dev_id || ""}
            @change=${this._changed("dev_id")}></ha-textfield>
          <ha-textfield label="title (accepts an en/zh map)" .value=${hmField(config.title)}
            @change=${this._changed("title")}></ha-textfield>
          <ha-textfield label="language (auto|en|zh, auto follows Home Assistant)"
            .value=${config.language || ""} @change=${this._changed("language")}></ha-textfield>
          <label class="sw">
            <ha-switch .checked=${config.show_topics === true}
              @change=${this._toggle("show_topics")}></ha-switch>
            <span>show_topics (show the MQTT topic of every row, for debugging)</span>
          </label>
          <label class="sw">
            <ha-switch .checked=${config.show_log !== false}
              @change=${this._toggle("show_log")}></ha-switch>
            <span>show_log (MQTT log row in Plan &amp; maintenance, off until switched on)</span>
          </label>
        </div>
      `;
    }
  }

  if (!customElements.get("hoymiles-g2-control-editor")) {
    customElements.define("hoymiles-g2-control-editor", HoymilesControlEditor);
  }
  if (!customElements.get("hoymiles-g2-control")) {
    customElements.define("hoymiles-g2-control", HoymilesControl);
  }

  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === "hoymiles-g2-control")) {
    window.customCards.push({
      type: "hoymiles-g2-control",
      name: "Hoymiles Control",
      description:
        "Buttons and inputs for every control topic of the Hoymiles micro storage "
        + "MQTT protocol (power, EMS mode, output power, phases, TOU, reboot).",
      preview: false,
    });
  }
}

if (customElements.get("ha-panel-lovelace")) {
  _hmControlRegister();
} else {
  customElements.whenDefined("ha-panel-lovelace").then(() => _hmControlRegister());
}
