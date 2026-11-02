/* ============================================================================
 * Hoymiles Micro Storage — sidebar panel
 * ----------------------------------------------------------------------------
 * `<hoymiles-panel>` is a ``panel_custom`` page registered by the integration,
 * one per config entry, so a device gets its own entry in the sidebar - the way
 * the vendor's own dashboard does it:
 *
 *     Home Assistant
 *     ├── Overview
 *     ├── RMI-1650A028FC22        <- this panel
 *     └── ...
 *
 * Layout mirrors the vendor app's device screen: a tab bar across the top and
 * one page per tab.
 *
 *   System   live power flow, today's energy tiles, power history, energy sankey
 *   Device   battery stack illustration, per-pack list, diagnostics
 *   Control  EMS mode / power setpoints / phases / TOU plan / reboot
 *
 * The page does not draw anything itself: it composes the Lovelace cards that
 * already ship with the integration (``hoymiles-power-flow``,
 * ``hoymiles-gauge``, ``hoymiles-history-chart``, ``hoymiles-energy-sankey``,
 * ``hoymiles-battery``, ``hoymiles-pack-list``, ``hoymiles-control``,
 * ``hoymiles-tou-editor``).  Those cards expose ``setConfig()`` rather than a
 * ``config`` property, so they are created imperatively and kept alive per
 * slot; only the active tab's cards exist, so a panel that is left open on the
 * System tab costs nothing on the Control tab.
 *
 * Panel config (set when the panel is registered):
 *   dev_id: RMI-1650A028FC22
 * ========================================================================== */

function _hmPanelRegister() {
  const LitElement = window.__hmLit && window.__hmLit();
  if (!LitElement) return;

  const html = LitElement.prototype.html;
  const css = LitElement.prototype.css;

  /* ------------------------------------------------------------------ *
   * Language
   *
   * The panel title in the sidebar is fixed at registration time (Home
   * Assistant has no hook to relocalise a panel title), so the title is the
   * device id and everything *inside* the panel follows the user's UI
   * language instead.
   * ------------------------------------------------------------------ */
  function hmLang(hass) {
    const ui = hass && hass.language;
    return ui && String(ui).toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  const T = {
    system: { en: "System", zh: "系统" },
    device: { en: "Device", zh: "设备" },
    control: { en: "Control", zh: "控制" },
    pv_today: { en: "PV today", zh: "今日发电量" },
    charged_today: { en: "Charged today", zh: "今日充电量" },
    discharged_today: { en: "Discharged today", zh: "今日放电量" },
    power_history: { en: "Power", zh: "功率" },
    soc_history: { en: "Battery SOC", zh: "电池电量" },
    energy_flow: { en: "Energy flow", zh: "能量流向" },
    battery_stack: { en: "Battery", zh: "电池" },
    packs: { en: "Battery packs", zh: "电池包" },
    diagnostics: { en: "Diagnostics", zh: "诊断信息" },
    settings: { en: "Settings & control", zh: "设置与控制" },
    tou: { en: "TOU plan", zh: "分时计划" },
    no_device: {
      en: "This panel is not linked to a device.",
      zh: "此面板未关联设备。",
    },
    loading: { en: "Loading…", zh: "加载中…" },
    model: { en: "Model", zh: "型号" },
    serial: { en: "Serial", zh: "序列号" },
    firmware: { en: "Firmware", zh: "固件版本" },
  };

  function t(lang, key) {
    const entry = T[key];
    if (!entry) return key;
    return entry[lang] || entry.en;
  }

  /** Stable slug, mirroring what Home Assistant does to entity ids. */
  function slug(value) {
    return String(value == null ? "" : value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  /* The cards this panel composes, in the order System needs them first. */
  const SYSTEM_CARDS = [
    "hoymiles-power-flow",
    "hoymiles-gauge",
    "hoymiles-history-chart",
    "hoymiles-energy-sankey",
  ];
  const DEVICE_CARDS = ["hoymiles-battery", "hoymiles-pack-list"];
  const CONTROL_CARDS = ["hoymiles-control", "hoymiles-tou-editor"];

  const COLORS = {
    pv: "#22c55e",
    battery: "#4a90d9",
    grid: "#f0a020",
  };

  class HoymilesPanel extends LitElement {
    static get properties() {
      return {
        /* ``hass`` is deliberately *not* listed: the panel needs a custom
         * setter (to push the state into the child cards immediately), and Lit
         * overwrites any accessor it finds on the prototype for a declared
         * property.  The setter calls ``requestUpdate()`` itself instead. */
        narrow: { type: Boolean },
        route: { type: Object },
        panel: { type: Object },
        _tab: { type: String },
      };
    }

    constructor() {
      super();
      this._hass = null;
      this._tab = "system";
      /* slot key -> the live card element. Reused across renders so switching
       * tabs does not rebuild a chart or restart the power flow animation. */
      this._cards = new Map();
      /* Card element names already waited on.  Per tab, because only the
       * active tab's cards are defined at first paint. */
      this._awaited = new Set();
    }

    /**
     * Take back a ``hass`` that Home Assistant assigned as a plain property.
     *
     * The frontend sets ``element.hass = ...`` right after creating the
     * element.  If the element happened to be created while the tag was not
     * defined yet (a slow first load), that assignment landed on the *instance*
     * and shadows the accessor below, so the panel would stay empty forever.
     * Deleting the own property exposes the accessor again; the value is then
     * re-assigned through it.
     */
    _adoptHass() {
      const own = Object.getOwnPropertyDescriptor(this, "hass");
      if (!own || !("value" in own)) return;
      const value = own.value;
      delete this.hass;
      if (value) this.hass = value;
    }

    connectedCallback() {
      super.connectedCallback();
      this._adoptHass();
    }

    /** Panel config, as registered by the integration. */
    _config() {
      return (this.panel && this.panel.config) || {};
    }

    _devId() {
      const config = this._config();
      if (config.dev_id) return String(config.dev_id);
      /* Fall back to the panel's url path so an older registration without a
       * config still shows something: the path is the slugified dev id.
       * ``url_path`` is a top-level field of the panel, not part of its config;
       * ``route.prefix`` is the same value as seen by the router. */
      const path =
        (this.panel && this.panel.url_path) ||
        (this.route && this.route.prefix) ||
        "";
      return String(path).replace(/^hoymiles-/, "");
    }

    _lang() {
      return hmLang(this._hass);
    }

    /** Device registry entry for this device, if Home Assistant knows it. */
    _deviceEntry() {
      const hass = this._hass;
      const devId = this._devId();
      if (!hass || !hass.devices || !devId) return null;
      for (const entry of Object.values(hass.devices)) {
        const identifiers = entry.identifiers || [];
        for (const pair of identifiers) {
          if (Array.isArray(pair) && pair[0] === "hoymiles" && pair[1] === devId) {
            return entry;
          }
        }
      }
      return null;
    }

    /** Entity id of ``<suffix>`` on this device (`null` when missing). */
    _entity(suffix, domain) {
      if (typeof window.__hmEntity === "function") {
        return window.__hmEntity(this._hass, this._devId(), suffix, domain);
      }
      return null;
    }

    /** ``{ entity, name, color }`` for the history chart, skipping misses. */
    _series(lang) {
      const wanted = [
        ["system_pv_power", lang === "zh" ? "光伏功率" : "PV power", COLORS.pv],
        ["system_battery_power", lang === "zh" ? "放电[+]/充电[-]" : "Discharge [+]/Charge [-]", COLORS.battery],
        ["system_grid_power", lang === "zh" ? "电网[+]/负荷[-]" : "Grid [+]/Load [-]", COLORS.grid],
      ];
      const series = [];
      for (const [suffix, name, color] of wanted) {
        const entity = this._entity(suffix);
        if (entity) series.push({ entity, name, color });
      }
      return series;
    }

    /** The three energy tiles, shaped like the vendor app's summary row. */
    _gauges(lang) {
      const tiles = [
        ["system_pv_energy_today", "pv_today", "☀️"],
        ["battery_discharge_energy_today", "discharged_today", "🔋"],
        ["battery_charge_energy_today", "charged_today", "⚡"],
      ];
      const out = [];
      for (const [suffix, key, icon] of tiles) {
        const entity = this._entity(suffix);
        if (!entity) continue;
        out.push({
          entity,
          config: {
            entity,
            name: t(lang, key),
            icon,
            scale: 0.001,
            unit: "kWh",
            decimals: 2,
            language: lang,
          },
        });
      }
      return out;
    }

    /**
     * Create (or fetch) the card for one slot.
     *
     * The config is only re-applied when it actually changed, because
     * ``setConfig`` clears the card's caches and would restart the power flow
     * animation on every parent re-render - which is once a second.
     */
    _card(key, tag, config) {
      let el = this._cards.get(key);
      if (!el || el.tagName.toLowerCase() !== tag) {
        if (!customElements.get(tag)) return null;
        el = document.createElement(tag);
        el._hmConfigKey = null;
        this._cards.set(key, el);
      }
      const signature = JSON.stringify(config);
      if (el._hmConfigKey !== signature) {
        if (typeof el.setConfig === "function") el.setConfig(config);
        el._hmConfigKey = signature;
      }
      el.hass = this._hass;
      return el;
    }

    /** Attach every card rendered in this pass to its placeholder. */
    updated() {
      const root = this.renderRoot;
      if (!root) return;
      for (const holder of root.querySelectorAll("[data-slot]")) {
        const key = holder.getAttribute("data-slot");
        const el = this._cards.get(key);
        if (el && el.parentNode !== holder) holder.appendChild(el);
      }
    }

    /** Wait until the card elements exist, then render them. */
    _ensureCards(tags) {
      const pending = tags.filter((tag) => !this._awaited.has(tag));
      if (!pending.length) return;
      for (const tag of pending) this._awaited.add(tag);
      Promise.all(pending.map((tag) => customElements.whenDefined(tag)))
        .then(() => this.requestUpdate())
        .catch(() => {
          /* A card that never defines itself should show the loading note
           * rather than stop the whole panel from rendering. */
          for (const tag of pending) {
            if (!customElements.get(tag)) this._awaited.delete(tag);
          }
        });
    }

    set hass(hass) {
      this._hass = hass;
      /* Push the new state down now instead of waiting for the next render:
       * the power flow card is designed to update on every 1 s push. */
      for (const el of this._cards.values()) el.hass = hass;
      this.requestUpdate();
    }

    get hass() {
      return this._hass;
    }

    /* ------------------------------- render ------------------------------- */

    static get styles() {
      return css`
        :host {
          display: block;
          background: var(--primary-background-color);
          min-height: 100vh;
        }
        .shell {
          max-width: 1180px;
          margin: 0 auto;
          padding: 12px 14px 32px;
        }

        /* --- header ---------------------------------------------------- */
        .head {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
          padding: 6px 4px 0;
        }
        .ident {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
        }
        .avatar {
          width: 38px;
          height: 38px;
          border-radius: 50%;
          background: #0303d8;
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
          font-size: 18px;
          flex: none;
        }
        .names {
          min-width: 0;
        }
        .title {
          font-size: 20px;
          font-weight: 600;
          color: var(--primary-text-color);
          letter-spacing: 0.2px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .sub {
          font-size: 12.5px;
          color: var(--secondary-text-color);
          margin-top: 2px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .spacer {
          flex: 1 1 auto;
        }
        .chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 12.5px;
          color: var(--secondary-text-color);
          border-radius: 999px;
          padding: 5px 11px;
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.12));
          white-space: nowrap;
        }

        /* --- tabs ------------------------------------------------------ */
        .tabs {
          display: flex;
          gap: 4px;
          margin: 14px 0 12px;
          padding: 4px;
          border-radius: 14px;
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.12));
          width: fit-content;
          max-width: 100%;
          overflow-x: auto;
        }
        .tab {
          appearance: none;
          border: none;
          background: none;
          cursor: pointer;
          font: inherit;
          font-size: 14px;
          font-weight: 500;
          color: var(--secondary-text-color);
          padding: 8px 18px;
          border-radius: 11px;
          white-space: nowrap;
          transition: background 0.15s, color 0.15s;
        }
        .tab:hover {
          color: var(--primary-text-color);
        }
        .tab[aria-selected="true"] {
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color);
          font-weight: 600;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
        }
        .tab:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 1px;
        }

        /* --- layout ---------------------------------------------------- */
        .page {
          display: grid;
          gap: 12px;
        }
        .row {
          display: grid;
          gap: 12px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        @media (max-width: 820px) {
          .row {
            grid-template-columns: minmax(0, 1fr);
          }
        }
        .note {
          font-size: 13px;
          color: var(--secondary-text-color);
          padding: 18px 4px;
        }
        .diag {
          display: grid;
          gap: 1px;
          background: var(--divider-color);
          border-radius: 12px;
          overflow: hidden;
        }
        .diag-row {
          display: flex;
          align-items: baseline;
          gap: 12px;
          justify-content: space-between;
          padding: 11px 15px;
          background: var(--card-background-color, #fff);
          font-size: 14px;
        }
        .diag-row .k {
          color: var(--secondary-text-color);
        }
        .diag-row .v {
          color: var(--primary-text-color);
          font-weight: 500;
          font-variant-numeric: tabular-nums;
          text-align: right;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      `;
    }

    _tabButton(id, lang) {
      return html`
        <button
          class="tab"
          role="tab"
          aria-selected=${this._tab === id ? "true" : "false"}
          @click=${() => {
            this._tab = id;
          }}
        >
          ${t(lang, id)}
        </button>
      `;
    }

    /** Render a card slot; shows the loading note until the element exists. */
    _slot(key, tag, config) {
      const el = this._card(key, tag, config);
      if (!el) return html`<div class="note">${t(this._lang(), "loading")}</div>`;
      return html`<div data-slot=${key}></div>`;
    }

    _systemPage(lang, devId) {
      const gauges = this._gauges(lang);
      const series = this._series(lang);
      return html`
        <div class="page">
          ${this._slot("power_flow", "hoymiles-power-flow", {
            dev_id: devId,
            language: lang,
            show_title: true,
            show_rssi: true,
          })}
          ${gauges.length
            ? html`<div class="row">
                ${gauges.map((tile, index) =>
                  this._slot(`gauge_${index}`, "hoymiles-gauge", tile.config)
                )}
              </div>`
            : ""}
          ${series.length
            ? this._slot("history_power", "hoymiles-history-chart", {
                dev_id: devId,
                language: lang,
                title: t(lang, "power_history"),
                range: "day",
                unit: "W",
                series,
              })
            : ""}
          ${this._slot("sankey", "hoymiles-energy-sankey", {
            dev_id: devId,
            language: lang,
            title: t(lang, "energy_flow"),
            range: "today",
            show_toolbar: true,
          })}
        </div>
      `;
    }

    _devicePage(lang, devId) {
      return html`
        <div class="page">
          ${this._slot("battery", "hoymiles-battery", {
            dev_id: devId,
            language: lang,
            show_title: true,
            show_history: true,
          })}
          ${this._slot("packs", "hoymiles-pack-list", {
            dev_id: devId,
            language: lang,
            title: t(lang, "packs"),
          })}
          ${this._diagnostics(lang)}
        </div>
      `;
    }

    _diagnostics(lang) {
      const entry = this._deviceEntry();
      const rows = [];
      if (entry && entry.model) rows.push([t(lang, "model"), entry.model]);
      if (entry && entry.sw_version) rows.push([t(lang, "firmware"), entry.sw_version]);
      const devId = this._devId();
      if (devId) rows.push([t(lang, "serial"), devId]);

      /* A couple of always-useful live readings next to the model.  Missing
       * entities are simply left out, so a device without a grid meter does not
       * show an empty row. */
      const extra = [
        ["battery_voltage", lang === "zh" ? "电池电压" : "Battery voltage"],
        ["battery_temperature", lang === "zh" ? "电池温度" : "Battery temperature"],
        ["grid_on_voltage", lang === "zh" ? "电网电压" : "Grid voltage"],
        ["rssi", lang === "zh" ? "信号强度" : "Signal"],
      ];
      for (const [suffix, label] of extra) {
        const entityId = this._entity(suffix);
        if (!entityId) continue;
        const state = this._hass && this._hass.states[entityId];
        if (!state) continue;
        const unit = (state.attributes && state.attributes.unit_of_measurement) || "";
        rows.push([label, `${state.state}${unit ? ` ${unit}` : ""}`]);
      }

      if (!rows.length) return "";
      return html`
        <div class="diag">
          ${rows.map(
            ([key, value]) => html`
              <div class="diag-row">
                <span class="k">${key}</span>
                <span class="v">${value}</span>
              </div>
            `
          )}
        </div>
      `;
    }

    _controlPage(lang, devId) {
      return html`
        <div class="page">
          ${this._slot("control", "hoymiles-control", {
            dev_id: devId,
            language: lang,
            title: t(lang, "settings"),
            show_phase: true,
            show_power_ctrl: true,
            show_log: true,
          })}
          ${this._slot("tou", "hoymiles-tou-editor", {
            dev_id: devId,
            language: lang,
            title: t(lang, "tou"),
          })}
        </div>
      `;
    }

    render() {
      if (!this._hass) return html``;
      const lang = this._lang();
      const devId = this._devId();

      if (!devId) {
        return html`<div class="shell"><div class="note">${t(lang, "no_device")}</div></div>`;
      }

      /* Only the cards of the active tab are needed; waiting for all of them
       * would delay the first paint for tabs the user may never open. */
      const needed = this._tab === "device"
        ? DEVICE_CARDS
        : this._tab === "control"
        ? CONTROL_CARDS
        : SYSTEM_CARDS;
      this._ensureCards(needed);

      const entry = this._deviceEntry();
      const subParts = [];
      if (entry && entry.model) subParts.push(entry.model);
      subParts.push(devId);

      return html`
        <div class="shell">
          <div class="head">
            <div class="ident">
              <div class="avatar">H</div>
              <div class="names">
                <div class="title">${devId}</div>
                <div class="sub">${subParts.join(" · ")}</div>
              </div>
            </div>
            <div class="spacer"></div>
            <span class="chip">Hoymiles · Micro Storage</span>
          </div>

          <div class="tabs" role="tablist">
            ${this._tabButton("system", lang)} ${this._tabButton("device", lang)}
            ${this._tabButton("control", lang)}
          </div>

          ${this._tab === "device"
            ? this._devicePage(lang, devId)
            : this._tab === "control"
            ? this._controlPage(lang, devId)
            : this._systemPage(lang, devId)}
        </div>
      `;
    }
  }

  if (!customElements.get("hoymiles-panel")) {
    customElements.define("hoymiles-panel", HoymilesPanel);
  }
}

/* The panel itself needs Lit like the cards do, but it must not wait for the
 * cards: it is the page. */
if (window.__hmWhenLit) {
  window.__hmWhenLit(() => _hmPanelRegister());
} else if (customElements.get("ha-panel-lovelace")) {
  _hmPanelRegister();
} else {
  customElements.whenDefined("ha-panel-lovelace").then(() => _hmPanelRegister());
}
