# Card reference

Complete option list for the eight Lovelace cards bundled with the
`hoymiles` custom integration.

**English** · [简体中文](CARDS.zh-Hans.md)

---

## How the cards are loaded

The integration registers the cards as frontend modules when it starts, so there
is **no "add resource" step** and no CDN is used. Add a card with
**Add card → Manual** and paste YAML, or add it directly to a dashboard YAML file.

After the integration is installed and Home Assistant has restarted, the cards
appear as `custom:hoymiles-*`.

Only one module is injected: `hoymiles-boot.js`, which imports the bootstrap, the
panel and the eight cards with static `import` statements. That keeps the
evaluation order fixed — `add_extra_js_url` stores URLs in a set, so registering
each file separately made the order arbitrary.

> Changed a card file? Hard-refresh the browser (`Ctrl` + `F5`).

---

## The sidebar panel

Adding the integration also registers a `panel_custom` page per device, so you do
**not** have to build a dashboard at all. It sits in the sidebar under the raw
`dev_id`, at `/hoymiles-<dev_id>`.

| Tab | Cards it composes |
|---|---|
| **System** | `hoymiles-power-flow`, three `hoymiles-gauge` tiles (PV / charged / discharged today), `hoymiles-history-chart` (PV, battery and grid power, day range), `hoymiles-energy-sankey` |
| **Device** | `hoymiles-battery`, `hoymiles-pack-list`, plus a diagnostics table (model, firmware, serial, live battery voltage / temperature, grid voltage, RSSI) |
| **Control** | `hoymiles-control`, `hoymiles-tou-editor` |

Points worth knowing:

- **It is a composition, not a second implementation.** Every widget inside the
  panel is one of the eight cards below, configured for the device. If you want a
  different layout, use the cards yourself.
- **Entity ids are resolved at runtime**, not hard-coded: the conventional
  `sensor.<slug(dev_id)>_<key>` id first, then a normalized scan, then the
  integration's `unique_id`. A card whose entity does not exist is simply left
  out, so a device without a grid meter shows no grid series.
- **The layout follows the UI language** of the viewing user; the sidebar title
  does not, because Home Assistant fixes a panel title when it is registered —
  that is why the title is the plain `dev_id`.
- **Only the active tab's cards exist.** Switching tabs reuses the card elements,
  so a chart is not rebuilt and the power-flow animation does not restart.
- Cards are created imperatively and their config is only re-applied when it
  actually changes. That matters because the panel re-renders once per second
  (the 1 s MQTT push) and `setConfig()` resets the card's internal caches.

There is nothing to configure: the panel is registered automatically when the
config entry is set up and removed when the last entry for that device is
unloaded.

## Options shared by every card

| Option | Type | Description |
|---|---|---|
| `dev_id` | string | Device identifier, `<client_prefix>-<SN>` (e.g. `MSA-280520260806`). Required on all cards except the gauge, which is entity-driven. |
| `language` | `zh` \| `en` | **Follows Home Assistant.** Leave it out and the card uses the language of the HA user viewing it (any `zh-*` code selects Chinese). Set it only to pin one card to a language. |
| `title` | string | Card heading. Defaults are per-card (see below). |
| `show_title` | bool | Set `false` to hide the heading (and, on some cards, the device SN). |

How `dev_id` is used: the card derives the entity ids it needs from it
(`sensor.<dev_id_slug>_<suffix>`). When your entities do not follow that pattern,
override them individually with the card's `entities:` map.

### How the language is chosen

1. An explicit `language: en` / `language: zh` in the card config wins. Use it only
   to pin one card to a language.
2. Otherwise the card follows the **Home Assistant user's** language, which each
   user sets in **Profile → Language**. Any code starting with `zh` (`zh-Hans`,
   `zh-Hant`, `zh-Hans-CN`) selects Chinese; everything else selects English.
3. Because it is resolved per render, changing the profile language updates every
   card live — no reload and no config change.

> This is why a shared dashboard reads correctly for an English and a Chinese user
> at the same time: the language is a property of the viewer, not of the card.

> `hoymiles-gauge` is the exception — it has no built-in wording at all. Every word
> on it comes from your own `name` / `label` / `icon`, so it never needs translating.

### Making your own text follow the language too

The language rule above covers the wording *inside* the cards. The text **you** write
in YAML - card titles, series names, gauge names, `balancer_label` - is yours, so the
card cannot translate it. It can, however, pick between the languages you supply:
write a **map** instead of a string.

```yaml
type: custom:hoymiles-history-chart
# instead of:  title: History
title:
  en: History
  zh: 历史数据
series:
  - entity: sensor.x_pv_power
    name:
      en: PV power
      zh: 发电功率
```

The card looks up the resolved language (`zh` or `en`). A map that is missing the
current language falls back to `en`, then to whichever entry exists, so a partial map
is never blank. A plain string keeps working exactly as before, which is why every
existing dashboard is unaffected.

Supported on these options:

| Card | Options that accept a map |
|---|---|
| all cards | `title` |
| `hoymiles-history-chart` | `title`, `series[].name` |
| `hoymiles-gauge` | `name`, `label` |
| `hoymiles-energy-sankey` | `title`, `balancer_label` |

> Because the visual card editor holds plain strings, a map shows there as an empty
> field and the label says `accepts an en/zh map`. Edit those options in the YAML
> editor (⋮ → *Edit in YAML*) rather than the visual one.

> Home Assistant's own cards - `markdown`, and the view/tab titles - belong to HA, not
> to this integration, so their text cannot follow the language. Keep those
> language-neutral, or pick one language for them.

### Why the view tabs cannot follow the language

Home Assistant resolves a view's tab label from `view.title` **without any
localization**:

```js
// home-assistant/frontend - src/data/lovelace/config/view.ts
computeViewTitle = (view, index) => view.title ?? (view.path ? titleCase(view.path) : String(index));
```

Contrast with HA's built-in Energy panel, which localizes its own tab titles by
generating the view from a *strategy* (`hass.localize(...)`) - a mechanism that
needs the whole view to come from JavaScript, so it is not worth coupling a
dashboard to it just for a label.

Two things follow, both easy to get wrong:

1. **A `view.title` is a fixed string.** There is no per-user language for it. If
   you want text that reads correctly for both audiences, write it bilingually -
   for example `System status / 系统状态`. A neutral heading inside the view
   (emoji + device SN) is the other option.
2. **Setting `icon` hides the title.** HA renders *either* the icon *or* the title
   unless you ask for both:

   ```js
   const icon_and_title = view.show_icon_and_title && view.icon && view.title;
   const icon_only = view.icon && !icon_and_title;
   ```

   So a view with an `icon` but no `show_icon_and_title: true` shows **only the
   icon** - the title survives merely as a tooltip. Add the flag when you want the
   icon and the label side by side.

---

## 1. `custom:hoymiles-power-flow`

Draws the system as a **wiring diagram**, the way the vendor app's system
screen does: one icon per branch, the unit in the middle, the grid tie point as
a junction dot, and thick rounded connectors carrying moving pearls. The icons
are the app's own artwork, embedded in the card.

```
⬜ PV1 ──┐                    ┌── ⬜ PV2
         ├── ▣ unit ───── ● ── ── ⬜ grid
⬜ storage ┘                  └── ⬜ load
                               └── ⬜ smart plug
```

- **The unit in the middle works as soon as anything flows through it**, so its
  artwork is the coloured one then and the dim one when the whole system is idle.
```yaml
type: custom:hoymiles-power-flow
dev_id: MSA-280520260806
title: 我的家
language: zh
```

| Option | Type | Default | Description |
|---|---|---|---|
| `dev_id` | string | — | **Required.** |
| `title` | string | localized *My home* | Heading text. |
| `show_title` | bool | `true` | `false` hides the title and the device SN, leaving only the signal icon. |
| `language` | `zh` \| `en` | *auto* | Pin the card's language. Omit it to follow the Home Assistant user's language. |
| `temperature_entity` | entity id | — | Outdoor temperature shown next to the title. |
| `show_rssi` | bool | `true` | Wi-Fi signal fan in the top-right corner. |
| `gradient` | bool | `true` | Draw the plain **white** backdrop the schematic sits on. `false` leaves the card background instead — pair it with a light theme, since the diagram's text colours are fixed. |
| `max_width` | number (px) | `620` | Maximum width of the illustration; it stays centred. |
| `flow_speed` | number | `1` | Speed multiplier for the moving pearls. `0.5` is calmer, `2` is faster. |
| `variant` | `inverter` | — | Set to `inverter` for the **micro-inverter layout** (see below). Empty keeps the four-branch storage schematic. |
| `image` | URL | *picked by SKU* | Product photo in the middle of the micro-inverter layout; must be a transparent cut-out. **Leave it out** — the card picks the cut-out from the serial's model code (see below) and an explicit value is only for overriding it. |
| `pv_count` | number | *auto* | DC inputs to draw in the micro-inverter layout, `1`–`4`: `1` gives a single `PV1`, `2` gives `PV1` + `PV2`, `4` draws through to `PV4` (a 4-in-1, whose middle two inputs rise into the photo's bottom edge). Omit to infer (see below). |
| `dim_when_idle` | bool | `true` | In the micro-inverter layout the photo fades to 55 % when nothing flows. `false` keeps it fully opaque. |
| `entities` | map | — | Entity overrides, keyed by suffix (see below). |

### Data sources

All values come from plain entity states — **the recorder is not required** — and
every branch reads the 1 s *quick state* system entity, the same numbers the
vendor app's system page shows:

| Node | Entity suffix (`sensor.<dev>_…`) |
|---|---|
| PV1 (top-left) | `sys_pv_p` |
| PV2 (top-right) | `sys_pv2_p` |
| Grid (right) | `sys_grid_p` (positive = importing) |
| Load (bottom-right) | `sys_load_p` |
| Smart plug (bottom-right, below load) | `sys_sp_p` |
| Storage (bottom-left) | `sys_bat_p` (negative = charging), falls back to `bat_p`; SOC from `sys_soc` |
| Status | `battery_status` (`standby` / `charge` / `discharge` / `lock`) |
| Signal fan | `rssi` (dBm) |

### Behaviour notes

- **A branch that carries power (`|P| >= 5 W`) is drawn in colour; an idle one
  uses the grey variant of the same icon**, which is how the app says "nothing
  happening here" without you having to read the number.
- A branch whose entity is **missing** (a slave unit reports no system level
  values) is left out entirely, together with its connector.
- The grid caption follows the flow: *Grid in* while importing, *Grid out*
  while exporting, plain *Grid* at ~0 W — it does not claim a direction it
  cannot see.
- The two diagonal branches (PV2 and load) are plain connectors - there is no
  direction arrow anywhere in the picture.  Which way the power goes is shown
  by the pearls, and only by them.
- A connector only shows moving pearls when that branch carries **≥ 5 W**,
  and the pearls always travel **with** the energy: out of PV1 / PV2, out of a
  discharging battery, in from a charging grid, back into a charging battery,
  out of the inverter when it feeds the house and back into it when the grid
  or the PV2 branch charges the battery, and into the load / smart plug.
  Pearl colour follows the branch, and speed rises with power.
- Travel time is computed from the **path length**, so a short stub and a long
  line look like the same speed - the fastest branch crosses in about 1.5 s,
  short stubs are held to a 1.0 s floor and a long line at low power takes at
  most 6 s. Tune the whole card with `flow_speed`.
- **The RSSI fan** uses four ascending bars; the number of lit bars indicates
  quality, with the `-21 dBm` reading next to it. Hovering shows a
  description:

  | RSSI | Bars lit |
  |---|---|
  | ≥ −55 dBm | 4 (excellent) |
  | ≥ −65 dBm | 3 (good) |
  | ≥ −75 dBm | 2 (fair) |
  | < −75 dBm | 1 (weak) |

  Hidden automatically when the device does not report `rssi`; disable with
  `show_rssi: false`.
- Override individual entities with the suffix-keyed `entities:` map:

  ```yaml
  entities:
    system_pv_power: sensor.my_pv_power
    system_battery_power: sensor.my_battery_power
    system_grid_power: sensor.my_grid_power
    system_load_power: sensor.my_load_power
    system_smart_plug_power: sensor.my_system_smart_plug_power
    soc: sensor.my_soc
    battery_status: sensor.my_battery_status
    rssi: sensor.my_rssi
  ```

### Sign conventions

`sys_grid_p` is **positive while importing** and the storage power is
**negative while charging**; the card normalises both before drawing. A node
carrying no power gets a grey ring — never a *standby* chip.

### Micro-inverter layout (`variant: inverter`)

A HiFlow is a grid-tied micro inverter with no battery and no off-grid port, so
the four-branch schematic spends half its area on branches the hardware does
not have. With `variant: inverter` the card draws only the ends it really has:

```
          ⬜ Grid port
               │
               └──── ▣ HiFlow Pro 2-in-1
             ⬜ PV1 ────┘
             ⬜ PV2 ────┘
```

That is: **photo centred, grid port top-right, PV-1 bottom-left and PV-2
bottom-right** — the same arrangement the vendor app uses on its device page.
Every node joins the photo's left and right edges through orthogonal connectors
with rounded corners, never crossing the unit.

A 4-in-1 unit (`pv_count: 4`) spreads the PV nodes into one row rather than
stacking them in the corners, so each input owns a position:

```
                          ⬜ Grid port
                               │
                          ▣ photo
                        ┌──┴─┬─┴──┐
       ⬜ PV1 ──────────┘    │    └────────── ⬜ PV4
                      ⬜ PV2 ┘    └ ⬜ PV3
```

The outer pair (`PV1` / `PV4`) takes the elbow down the left and right edge; the
inner pair (`PV2` / `PV3`) has no side edge left to use, so it **rises straight
into the photo's bottom edge**. Giving every input its own position is what
stops the row from reading as "one is missing". Three inputs (`pv_count: 3`) is
the middle form: one elbow each side, one riser in the centre.

```yaml
- type: custom:hoymiles-g2-power-flow
  dev_id: RMI-4161A0209FF6
  variant: inverter
  # image is left out on purpose: the card picks the cut-out from the SKU
  pv_count: 2                 # 2-in-1: PV1 + PV2. Set 1 for a single-input unit.
  title: My home
  show_title: false
  max_width: 700
```

- **`pv_count` decides how many DC inputs are drawn, and it is inferred when
  omitted.** A HiFlow Pro 2-in-1 has two PV ports, a plain HiFlow has one, and
  getting it wrong does not merely omit a line — it adds a node that can never
  show a reading. Resolution order: explicit `pv_count` → a live `pv2_power` /
  `system_pv2_power` → the model name (contains `Pro` ⇒ 2, contains `HiFlow`
  ⇒ 1) → 1. If your unit is misclassified, set `pv_count`; no code change needed.
- **`PV1` / `PV2` are the unit's own DC inputs**, not third-party modules.
  Third-party PV feeding the system is folded into the `system_pv_power` total
  and deliberately does **not** become a `PV3` node — the inverter only has two
  physical inputs.
- The **grid port always shows an absolute value** with a fixed `Grid port` caption, so
the number never flips sign. Direction is carried by the moving pearls and the
connector colour instead: `> 0` is importing (pearls run towards the unit, blue
line), `< 0` is exporting (pearls run towards the grid, amber line). The grid
node is **always drawn**, even at 0 W or with no reading (`—`), because "no grid
reading" and "0 W on the grid" are entirely different facts.
- The middle is the real product photo, centred and sized as
  `min(300, 190 × aspect)`, where the aspect ratio is looked up by file name in
  `IV_PHOTO_ASPECT` (`hiflow.png` = 736/486, `hiflow-800.png` = 189/168,
  `hiflow-pro-1in1.png` = 237/168, `hiflow-pro-2in1.png` = 360/168,
  `hiflow-pro-4in1.png` = 366/168, falling back to `360/168`). Connector ends
  stop 22 px inside the photo's left/right edges (`IV_TERMINAL_INSET`) instead
  of touching the border.
- **The artwork follows the SKU — do not set `image` just to pick a photo.** The
  photo is part of the diagram rather than decoration (every connector stops on
  its edge), so a 4-input unit has to show a 4-input body or the two middle
  risers appear to end in mid-air. `IV_IMAGE_BY_CODE` therefore maps the first
  four digits of the serial to the matching cut-out:

  | SKU | Model | Photo |
  | --- | --- | --- |
  | `1650` | HiFlow | `hiflow-800.png` |
  | `4160` | HiFlow Pro 1-in-1 | `hiflow-pro-1in1.png` |
  | `4161` | HiFlow Pro 2-in-1 | `hiflow-pro-2in1.png` |
  | `4162` | HiFlow Pro 4-in-1 | `hiflow-pro-4in1.png` |

  An unknown SKU falls back to `IV_IMAGE_BY_COUNT` (the resolved port count),
  then to the 2-in-1 default. An explicit `image:` still wins over both, which
  is what lets a dashboard override the artwork without a code change.
- The canvas is a fixed `700 × 430`. All coordinates live in the `IV_*` constants
at the top of the file (`IV_NODE_PV1`, `IV_NODE_PV2`, `IV_NODE_GRID`,
`IV_PHOTO_CX`, `IV_PHOTO_CY`, `IV_CORNER`), so nudging a node never touches the
drawing logic. The grid port's caption is drawn *above* its ring so it cannot
overlap the photo.
- Below `|P| = 5 W` the photo fades to 55 %; `dim_when_idle: false` disables it.
- No battery, load, smart-plug or off-grid node — the micro inverter has no such
topics.
- **The variant is never auto-detected.** The same card also draws the `system`
  view of a storage device, and sniffing the `RMI-` serial prefix would silently
  change those views too. Only an explicit `variant: inverter` switches drawings.

---

## 2. `custom:hoymiles-battery`

Draws the physical battery stack module by module, so the picture always matches
how many packs are actually installed (1–4), each with its own SOC and
temperature callout alternating left / right. The illustration follows the
product photos: one body with a single light-to-dark gradient, thin seams
between the modules, the brand badge on the first module, and a dark head
drawing the hardware's **display bar** — the power symbol, the PV reading with
its SOLAR caption, the SOC between two chevrons, and the battery reading with
its BATTERY caption. The drawn unit is a clean rectangle: no side panel, no
feet.

  - SOLAR and BATTERY show **this unit's own** `pv_power` / `bat_power` (the
    panel depicts the device itself); the corner callouts keep the system level
    readings. The values are shown as they are — no zero padding — and clamp at
    four digits (9999 W).
  - **The chevrons are the charge / discharge indicator**: charging draws the
    left one, discharging the right one, both in white, and an idle battery
    draws neither. Charging is negative battery power, matching the firmware.

The head module is also where the **host temperature** is called out.

```yaml
type: custom:hoymiles-battery
dev_id: MSA-280520260806
title: HiBattery 4020 X
language: zh
```

| Option | Type | Default | Description |
|---|---|---|---|
| `dev_id` | string | — | **Required.** |
| `title` | string | detected model | Overrides the model read from the device registry. |
| `show_title` | bool | `true` | `false` hides the heading. |
| `language` | `zh` \| `en` | *auto* | Pin the card's language. Omit it to follow the Home Assistant user's language. |
| `show_history` | bool | `true` | Optional history section (needs the recorder). |
| `show_host_temp` | bool | `true` | `false` hides the head unit temperature. |
| `max_width` | number (px) | `560` | Maximum width of the illustration. |
| `alarm_entity` | entity id | — | Shows a bell next to the title while this entity is `on`. |
| `entities` | map | — | Entity overrides (see below). |

| `entities` key | Meaning |
|---|---|
| `pack_count` | Number of installed packs |
| `pv` | PV power |
| `grid_on` | On-grid port power |
| `grid_off` | Off-grid / EPS port power |
| `battery` | Battery power |
| `battery_status` | Battery status |
| `soc` | System SOC |
| `pack<N>_soc` | Per-pack SOC |
| `pack<N>_temperature` | Per-pack temperature |
| `battery_temperature` | Firmware's own battery temperature (head temperature fallback) |

### Behaviour notes

- **The title defaults to the model in the device registry** — in our test unit
  that is `HiBattery 4020 X`, taken from the firmware's MQTT discovery
  `device.model`. Different model, no config change; an explicit `title` wins.
- Pack count prefers the `pack_count` sensor (from `pack_num` in
  `device/state`) and falls back to counting how many `pack1_soc`…`pack4_soc`
  actually report a value. The upper bound is 4, matching the firmware's own
  truncation.
- Per-pack values use `pack<i>_soc` / `pack<i>_temperature`; the surrounding
  powers use `pv_power`, `grid_on_power`, `grid_off_power`, `battery_power`.
- **The head unit temperature is the average of the installed packs**, drawn as
  one more callout in the same style as the per-pack ones — the head has no
  sensor of its own, so the vendor app shows the same measure. Packs that report
  no temperature are skipped, and if none of them do the firmware's
  `battery_temperature` (`bat_temp`) is used instead. `show_host_temp: false`
  removes the callout.
- The signal bars next to the title are derived from `rssi` (dBm).
- The history section (optional) reads long-term statistics via
  `recorder/statistics_during_period`, plotting pack SOC and summarising charge /
  discharge energy for the range. If the recorder is off you only get a notice —
  the rest of the card still works.

---

## 3. `custom:hoymiles-pack-list`

A compact alternative to the battery illustration: one row per pack, SOC bar on
the left, SOC percentage and heating flag on the right. Pack count follows the
same rule as the battery card.

```yaml
type: custom:hoymiles-pack-list
dev_id: MSA-280520260806
language: zh
title: 电池电量
columns: 2
show_temperature: false
```

| Option | Type | Default | Description |
|---|---|---|---|
| `dev_id` | string | — | **Required.** |
| `title` | string | localized *Battery* | Heading text. |
| `language` | `zh` \| `en` | *auto* | Pin the card's language. Omit it to follow the Home Assistant user's language. |
| `columns` | number | `1` | Lay the rows out in N columns. Omit for a single column. |
| `show_temperature` | bool | `true` | `false` shows SOC only, dropping the ℃ reading. |

---

## 4. `custom:hoymiles-history-chart`

Day / month / year curves with date navigation, drawn like the vendor app's
history pages. Positive values stack upward from the zero line and negative
values stack downward, so a charge/discharge sensor reads naturally on both sides
of the axis.

```yaml
type: custom:hoymiles-history-chart
dev_id: MSA-280520260806
title: 历史数据
language: zh
range: day
height: 330
unit: W
series:
  - entity: sensor.x_pv_power
    name: 发电功率
    color: "#22c55e"
  - entity: sensor.x_system_battery_power
    name: 放电[+]/充电[-]
    color: "#4a90d9"
```

| Option | Type | Default | Description |
|---|---|---|---|
| `series` | list | — | **Required.** One entry per curve: `entity`, `name`, `color`. |
| `dev_id` | string | — | Optional when every series names an explicit `entity`. |
| `title` | string | — | Card heading. |
| `language` | `zh` \| `en` | *auto* | Pin the card's language. Omit it to follow the Home Assistant user's language. |
| `range` | `day` \| `month` \| `year` | `day` | Initial time range. |
| `height` | number (px) | `330` | SVG height. |
| `unit` | string | — | Y-axis unit label. Auto-promotes to kW above 1.5 kW. |
| `zero_line` | bool | `true` | Draw the zero line. |
| `symmetric` | bool | `true` | `false` draws a bottom-up axis from min to max — use it for SOC. |
| `stack` | bool | = `symmetric` | `false` overlays the curves instead of stacking them. Leave it off for a *level* (SOC, temperature); stack only series that add up (power, energy). |
| `min` / `max` | number | — | Fixed axis limits. |
| `span` | number | — | Fixed half-range when `symmetric` is on. |
| `sync_group` | string | — | Cards sharing a group share their time window (range + date). |
| `show_toolbar` | bool | `true` | `false` hides this card's own time controls — use it on the followers. |

### Behaviour notes

- **Data comes from `recorder/statistics_during_period`** (long-term statistics),
  so no administrator rights are needed and the database file is never touched.
- The time selector matches the vendor app: a date pill (`‹` `›` around the date)
  top-left, a day/month/year dropdown top-right, and rounded pill legends below
  the curve.
- Axis ticks pick their decimal places from the actual step, so a 1.25 kW step
  shows `1.25` instead of rounding to `1`.
- Fixing `span` / `min` / `max` keeps the same scale across different days, which
  makes side-by-side comparison possible.
- **Stacking follows the axis unless you say otherwise.** Power and energy
  series stack, because `charge + discharge` is a sum worth reading as a total.
  A *level* must never stack: three packs at 81 % would be drawn at 0..81 %,
  81..162 % and 162..243 %, so on a 0..100 axis only the first pack stays
  visible. `symmetric: false` (the SOC / temperature axis) therefore overlays
  by default; `stack: true` / `false` overrides it either way.
- **Click a legend entry to highlight that curve** — the selected curve thickens
  and brightens while the others fade back. Click it again (or click the chart)
  to clear. The tooltip dims faded curves to match.
- **Hovering shows a guide line and a tooltip at the same instant on every chart
  in the same `sync_group`** (for example *History* driving *Battery SOC*).
  Matching is by timestamp, so charts with different bucket sizes or data gaps
  still line up.
- `show_toolbar: false` plus `sync_group` gives you a dashboard where one chart
  controls and the others follow.
- A card removes itself from its group when it is deleted, leaving nothing behind.

---

## 5. `custom:hoymiles-gauge`

A stat tile: title and icon on top, big value in the middle, and one green arc at
the bottom filled by the value's share of `min`…`max`, with the percentage printed
inside the arc.

```yaml
type: custom:hoymiles-gauge
entity: sensor.msa_280520260806_battery_charge_energy_today
name: 今日充电量
unit: kWh
scale: 0.001
max: 10
min: 0
decimals: 2
icon: ⚡
label: 自发自用率
color: "#22c55e"
```

| Option | Type | Default | Description |
|---|---|---|---|
| `entity` | entity id | — | **Required.** Drives the big readout. |
| `name` | string | entity name | Title. |
| `unit` | string | entity unit | Display unit. |
| `scale` | number | `1` | Multiplier applied before display. `0.001` turns Wh into kWh. |
| `max` | number | — | Upper limit **in display units**. Omit to let the arc grow with the value. |
| `min` | number | `0` | Lower limit. |
| `decimals` | number | `2` | Decimal places in the readout. |
| `icon` | string | — | Emoji / glyph shown next to the title. |
| `label` | string | — | Caption under the percentage. |
| `color` | CSS colour | `#22c55e` | Arc colour. |
| `show_arc` | bool | `true` | `false` drops the arch and its percentage, leaving a plain readout. |

### Ratio mode

When the interesting number is a ratio between entities rather than a share of an
invented ceiling, give the arc its own source. The big readout still shows
`entity`; only the arc and its percentage come from the ratio.

| Option | Description |
|---|---|
| `percent_numerator` | Required for ratio mode. |
| `percent_subtract` | Optional, taken off the numerator. |
| `percent_denominator` | Optional, defaults to the numerator. |

```yaml
type: custom:hoymiles-gauge
entity: sensor.msa_280520260806_system_pv_energy_today
name: 今日发电量
unit: kWh
scale: 0.001
icon: ☀️
label: 自发自用率
percent_numerator: sensor.msa_280520260806_system_pv_energy_today
percent_subtract: sensor.msa_280520260806_grid_on_energy_out_total
percent_denominator: sensor.msa_280520260806_system_pv_energy_today
```

Self-consumption = *PV energy − exported energy* ÷ *PV energy*.

### Behaviour notes

- Percentage = `(value − min) / (max − min) × 100`, rounded to a whole number,
  clamped to 0–100 %.
- While the entity has no data yet the arc is still drawn empty and the value and
  percentage read `—`, so the card never turns into a blank space.
- Set `max: 100` and point it at a SOC sensor for a battery-percentage tile.

---

## 6. `custom:hoymiles-control`

Every command in section 10–20 of the MQTT protocol guide, as buttons and inputs.
Commands are published **straight to the protocol topics** (qos 1, retain false),
so the card keeps working even if a discovery entity is missing or offers a
narrower option list than the protocol allows. Current values are read back from
the matching entities when they exist.

```yaml
type: custom:hoymiles-control
dev_id: MSA-280520260806
language: zh
title: 设备控制
```

| Option | Type | Default | Description |
|---|---|---|---|
| `dev_id` | string | — | **Required.** |
| `title` | string | localized *Control* | Card heading. |
| `language` | `zh` \| `en` | *auto* | Pin the card's language. Omit it to follow the Home Assistant user's language. |
| `show_power_ctrl` | bool | `true` | `false` hides the *Power control* row. |
| `show_phase` | bool | `true` | `false` hides the *Per-phase output power* row. |
| `show_log` | bool | `true` | `false` hides the *MQTT log* row (the log itself is off by default). |
| `show_topics` | bool | `false` | Show the MQTT topic under each row (debugging). |
| `subtitle` | bool | `true` | `false` hides the grey line next to the title. |

### Rows and topics

| Row | Protocol topic | Notes |
|---|---|---|
| Device on/off | `switch/<dev_id>/set` | `ON` / `OFF` |
| EMS mode | `select/<dev_id>/ems_mode/command` | `general` / `mqtt_ctrl` / `tou_plan`; unsupported options are greyed out |
| Power control | `number/<dev_id>/power_ctrl/set` | Only effective in `mqtt_ctrl` mode, and it is a *lease*: the device drops it after ~60 s and falls back to `output_power`. Use the *Re-send timer* row to hold it. |
| Re-send timer | the integration re-sends `number/<dev_id>/power_ctrl/set` every N s | Off by default. On, it publishes the current power-control value on a period (5–60 s in the card, default 30 s) so the lease never lapses. **The beat runs inside Home Assistant, not in the browser** - navigating away, reloading, closing the tab, or closing the browser entirely does not stop it. The card is only a remote control for that background beat and reads its state back from `sensor.<dev_id>_power_control_keep_alive`. Stops when switched off or when the EMS mode leaves `mqtt_ctrl`; it also stops itself after 5 consecutive publish errors and records the reason. Disabled outside `mqtt_ctrl`. **The 60 s ceiling is enforced by the card only; the backend service still accepts 5–3600 s** so existing automations keep working. |
| Output power | `number/<dev_id>/output_power/set` | Full-load output ceiling (W) |
| Per-phase output power | `number/<dev_id>/phase_output_power/set` | Sent as `{"phase_a":..,"phase_b":..,"phase_c":..}` |
| Fetch TOU plan | `sensor/<dev_id>/tou_plan/get` | The reply is published on `tou_plan/status` |
| Reboot | `button/<dev_id>/reboot/trigger` | Sends `RESTART` after a confirmation |
| MQTT log | *(subscribes only, sends nothing)* | Off by default; on, it streams what the device reports and what HA sends, with retained messages labelled |

### MQTT log

The last row of *Plan & maintenance* is an **MQTT log**, **off by default**. Turning it
on subscribes to two wildcards over the Home Assistant websocket (the
`mqtt/subscribe` command) and interleaves both directions on one timeline:

| Wildcard | Carries |
|---|---|
| `homeassistant/+/<dev_id>/#` | what the device publishes (`quick/state` every second, `device/state`, `system/state`, `tou_plan/status`, the discovery configs) plus what HA sends (`set`, `command`, `trigger`, `get`) |
| `hoymiles/<dev_id>/#` | the integration's own topics (`availability`, the EMS mode echo) |

- Direction is read off the topic: the command side (`/set`, `/command`,
  `/trigger`, `/get`) is *HA → device*, everything else on those trees is
  *device → HA*, and the `hoymiles/` family belongs to this end as well.
- **Retained messages are labelled, not hidden.** A retained MQTT message lives
  on the broker and is replayed the instant anything subscribes — so an offline
  unit still "sends" one, and an earlier build stamped it with its *receipt*
  time, making an offline device look like it had just reported. Such rows now
  show `—` instead of a clock and carry a grey italic *retained · cached* badge
  (with a tooltip). They are **annotated, not dropped**: the `attributes`
  capability list only ever arrives retained, so filtering them would leave a
  log full of blank payloads.
- Every row shows the time, a direction badge, the topic with the boilerplate
  stripped (`sensor/quick/state`; the full topic is the tooltip) and the payload,
  pretty printed when it is JSON and truncated when it is long.
- The list keeps the **latest 200 messages** (a `quick/state` a second is about
  three minutes), counts what it dropped, and scrolls to the newest message
  unless you have scrolled up to read.
- While it is off **nothing is subscribed**, so the card costs nothing; leaving
  the view unsubscribes and coming back resumes it.
- We could not make this cheaper: `mqtt/subscribe` is **admin-only** in Home
  Assistant, so a non-admin user sees an explanation instead of a stream.

### Behaviour notes

- Range hints such as `-1000 ~ 1000 W` prefer the entity's `min` / `max`
  attributes, falling back to protocol defaults.
- **Pin `entities:` when a device has several `number` entities — but the card
  now gets it right unpinned too.** `power_ctrl` and `output_power` are sibling
  `number` entities and either can end up as `number.<dev>` or
  `number.<dev>_2`. *Which is which varies per firmware*: measured, FF6
  (2-in-1) uses `_2` for `power_ctrl`, FC22 (single-input) is the other way
  round, and a storage unit puts `power_ctrl` on the base entity. So the suffix
  order is **not** a reliable signal. What *is* stable is the range each entity
  declares: `power_ctrl` has a floor at or below zero (it can curtail to
  nothing, and a storage unit also charges / exports negative), while
  `output_power` starts at the hardware minimum, 100 W on every model measured.
  The card therefore tests `min` first (`min <= 0` ⇒ `power_ctrl`, `min > 0` ⇒
  `output_power`), falls back to the suffix order only when the candidates are
  not unique, and an explicit `entities:` pin always wins. If a row still shows
  obviously wrong bounds (e.g. *Output power* showing `0~132`), that pin is
  what is missing.
- **The power switch shows "last sent", it never pretends to know the state.**
  The firmware does publish a `state_topic`, but its payload is a nested JSON
  document (`device/state`) that can never equal `ON` / `OFF`, so the
  integration's discovery override deliberately strips it
  (`discovery_override.py`, `_patch_switch`) and the entity becomes optimistic.
  Consequence: the `ON` / `OFF` it shows is **Home Assistant remembering its own
  command**, not the device answering — it resets to `unknown` on restart and
  cannot tell you whether the unit is running. The card therefore says *last
  sent: on / off (the device does not report its switch state)* or *nothing sent
  yet — the device does not report its switch state.* To check whether the unit
  is actually up, use the power-flow card in the `device` view: **non-zero PV
  power proves it is awake and producing even while the switch row reads off.**
  (An earlier version added a *Device read-back* row here; it was removed — the
  same numbers are larger and clearer in the `device` view's power-flow card,
  and repeating them on the control page was just noise.)
- **The card remembers the last values you sent, so a reload no longer needs a
  re-dial.** As said above, `power_ctrl`, `output_power` and the power switch
  have no usable state topic, so their entities read back as `unknown`. Seeding
  the form from entities alone meant every visit to the `control` view started
  with empty sliders and the default period — the user had to power the unit on,
  re-set both wattages and re-enter the period every single time. The card
  therefore also stores **the last values sent from this browser** in
  `localStorage`, under `hoymiles-g2-control:<dev_id>`:

  ```json
  { "switch": "on", "ems_mode": "power_ctrl", "power_ctrl": 200,
    "output_power": 300, "timer_period": 45, "at": 1793774422400 }
  ```

  It is written only on a real send (the power switch writes `switch`, an actual
  dispatch writes the matching field, setting the period writes `timer_period`);
  nothing is polled or saved in the background. Seed priority, highest first:
  **① the wattage held by a running keep-alive** (server-side truth from the
  integration — it overrides the browser's memory and writes back to it) →
  **② the current HA entity value** (only when not `unknown` / `unavailable`) →
  **③ the `localStorage` memory** → **④ `power_ctrl` falls back to
  `output_power`**. Remembered values only **refill the form**: opening the page
  never re-sends anything and produces no MQTT traffic. Two limits: the memory is
  **per browser** (a different browser, a private window or clearing site data
  loses it — expected, not a bug), and the keep-alive period reported by the
  sensor is trusted **only while a beat is actually running**; when idle that
  sensor reports the built-in default, and taking it at face value would silently
  undo a period the user had chosen earlier.

- The layout follows the iOS settings idiom: rounded groups, small grey section
  headers (**Power & mode / Power settings / Plan & maintenance**), rows of
  icon + name + right-aligned control, and hairlines that stop short of the card
  edge. On/off and EMS mode use segmented controls; reboot is red.
- **Power on/off is slow** — the firmware has to bring the PCS (and the packs)
  down or up. The card shows the requested state as *pending* for up to 5 s until
  the device reports it, then keeps a tick visible for a moment.
- MQTT topics are hidden by default because they are engineering detail that
  crowds out the content; enable `show_topics: true` when debugging.
- **A blank box stays blank — it is never read as zero.** `Number("")` is `0` in
  JavaScript and `Number.isFinite(0)` is `true`, so an earlier build rendered a
  cleared or never-filled field as `0`, which looks like a real value; one stray
  press of *Send* then published `output_power = 0` and the device obediently
  stopped producing. Blankness is now detected **before** any coercion: the
  number box is genuinely empty with a grey *not set* placeholder, the range
  input parks at the low bound (a drawing position only, never read back as the
  user's value), and `_draftNumber()` returns `null` for an empty or
  whitespace-only draft. Every send path (power control, output power, phase
  output, arming the timer) treats `null` as *invalid value* and publishes
  nothing at all.
- The **MQTT log** (see above) is a per-card switch, not a global one: it is off
  until you turn it on, and `show_log: false` removes the row entirely.
- **The timer says nothing while it is on.** Its sub-line used to read
  *"re-sending every 30 s · 12 sent · last 10:04:11"*, rewritten on every state
  push — jitter, and enough height that it once pushed the sub-line out of the
  clipped row entirely. With the timer running, the segment already reads *On*
  and the box already shows the period, so restating it is noise. Only the two
  states that need a word keep one: not armed (*switch EMS to mqtt_ctrl first*)
  and failed (the integration's error, translated into a sentence you can act on).
- **The re-send timer is not a browser timer.** An earlier version armed a
  `setTimeout` inside the card, which worked until you left the dashboard: the
  element was removed from the DOM, the timer died with it, and the device
  reverted to `output_power` a minute later with nothing on screen explaining
  why. The beat now lives in the integration (`keepalive.py`), so it keeps
  running with no dashboard open, and the card only mirrors it. Two consequences
  worth knowing: two browsers cannot fight over it (there is one beat per
  device), and the row is honest right after a reload because it reads the
  entity's attributes rather than a local flag.
- **The re-send period is capped at 60 s by the card.** The input declares
  `min=5 max=60`, and anything above 60 — or unparsable, zero or negative — is
  clamped: `120 → 60`, `9999 → 60`, blank → 30, `0 → 30`. The clamped value is
  then **written back into the field**, because otherwise typing 120 into a box
  already reading 60 would leave 120 on screen while only 60 was in effect,
  making the ceiling look broken. **The backend service still accepts 5–3600 s**
  (`services.py`, `vol.Range(min=5,max=3600)`); that is deliberate, so existing
  automations keep working — the ceiling is enforced only in this card's UI.
- **"Switch EMS to mqtt_ctrl first" can appear while the EMS row still reads
  `mqtt_ctrl`.** The select's state topic is a retained value that the firmware
  only refreshes on its own slow schedule, so it can lag behind the mode the
  device is really in. The keep-alive trusts what the device *reports* (and
  refuses to send otherwise, since a device in another mode ignores
  `power_ctrl`), and the error text names the mode the device actually reported.
  Measured on FF6: after commanding `mqtt_ctrl` the device still self-reported
  `general` in two independent long-window probes, and `power_ctrl` was then
  ignored outright. When debugging, read
  `sensor.<dev_id>_ems_mode_device` (the device's own `device/state`), never
  `select.ems_mode` — the latter is the integration echoing your command back.

---

## 7. `custom:hoymiles-tou-editor`

The visual TOU plan editor. It talks to the device through the integration
services (`hoymiles.set_tou_day_plan`, `set_tou_week_plan`, `get_tou_plan`,
`set_ems_mode`) and falls back to `mqtt.publish` if the integration is somehow
absent.

```yaml
type: custom:hoymiles-tou-editor
dev_id: MSA-280520260806
language: zh
```

| Option | Type | Default | Description |
|---|---|---|---|
| `dev_id` | string | — | **Required.** |
| `title` | string | localized | Card heading. |
| `language` | `zh` \| `en` | *auto* | Pin the card's language. Omit it to follow the Home Assistant user's language. |
| `require_tou_mode` | bool | `true` | The editor only renders while EMS mode is `tou_plan`. Set `false` to disable that gate. |
| `ems_entity` | entity id | auto | Override the entity used to read EMS mode. |
| `status_entity` | entity id | auto | Override the entity used to read the plan status. |
| `day_ack_entity` | entity id | auto | Override the day-plan acknowledgement entity. |
| `week_ack_entity` | entity id | auto | Override the week-plan acknowledgement entity. |

### Behaviour notes

- A day is a list of segments with `mode` / `ts` / `te` / `sh` / `sl` / `pc` / `pd`.
  `ts` and `te` are quarter-hour slots, `0`–`96`.
- Modes: `1` force charge, `2` PV charge, `4` discharge.
- The card writes `day1`…`day8`, then the week plan, then switches EMS mode to
  `tou_plan`, then reads the current day back.
- The plan editor has its own UI config editor, so it can also be added and
  configured graphically from the dashboard.

> **Why the EMS gate exists.** Early firmware shipped no `state_topic` for
> `ems_mode`, so the integration maintains a **retained state topic** of its own
> at `hoymiles/<dev_id>/ems_mode/state`:
>
> - as soon as anyone publishes to `…/ems_mode/command`, the integration echoes
>   it to that topic, so the UI and cards refresh immediately;
> - it also follows `ems_mode` inside `system/state` (the device's real running
>   mode, on a 5-minute cycle) and corrects itself, so a device-side timeout back
>   to `general` shows up.
>
> Why not just point `state_topic` at `system/state`: that topic only arrives
> every 5 minutes, and this card gates on the select state, which would leave the
> editor stuck for up to 5 minutes after switching to `tou_plan`.

---

## 8. `custom:hoymiles-energy-sankey`

A source → sink energy-flow sankey built from long-term statistics.

```yaml
type: custom:hoymiles-energy-sankey
dev_id: MSA-280520260806
title: 能量流
language: zh
range: today
```

| Option | Type | Default | Description |
|---|---|---|---|
| `dev_id` | string | — | **Required.** |
| `title` | string | localized | Card heading. |
| `language` | `zh` \| `en` | *auto* | Pin the card's language. Omit it to follow the Home Assistant user's language. |
| `range` | `today` \| `7d` \| `30d` \| `month` | `today` | Time range. |
| `balancer_label` | string | localized | Name of the *Loss* / *Unmetered* residual node. |
| `show_toolbar` | bool | `true` | `false` hides the range switcher. |
| `ribbon_gap` | number (px) | `3` | White gap between ribbons. |
| `ribbon_opacity` | number | `0.5` | Ribbon opacity, 0–1. |
| `icons` | map | — | Per-node emoji overrides, e.g. `pv: "☀️"`. |
| `statistics` | string \| list \| map | — | Override the default `statistic_id`s. A value may be a single id or a list; multiple ids are summed. |

### Data source

The card calls Home Assistant's official WebSocket statistics endpoint:

```
recorder/statistics_during_period
  statistic_ids: [...]       # this device's energy sensors
  period: "day"
  units: {energy: "kWh"}     # unit conversion done server-side
  types: ["change"]          # HA's already-computed delta for the range
```

Therefore:

- The recorder **database file is never touched** — no SQLite reads, no exposure
  to schema migrations.
- **No administrator rights** are required (`statistics_during_period` is not
  admin-gated).
- Only the recorder integration is needed, and it is part of `default_config`.
- Rendering is hand-rolled SVG with **no CDN**, so it works offline.

### Interaction

Click a ribbon to highlight that single flow, or click a node box to highlight
every ribbon touching it. The rest of the diagram dims and a detail panel lists
the involved flows. Click the same target again (or empty space) to clear. This
is view state only — the numbers never change.

### About the "Loss / Unmetered" node

A sankey requires conservation, but the device meters every port **separately**
(conversion losses, sampling phase, unmetered loads all create a difference).
Rather than normalising and scaling the flows, the card draws the difference as
an explicit node — a positive residual becomes *Loss*, a negative one becomes
*Unmetered* — which keeps the diagram conserved and every ribbon truthful.

### Rendering caveat

Each side is a single column of node boxes. Because the device meters each port
separately, the routing behind the ribbons is **not measured**: it is estimated by
spreading each source over the sinks proportionally (iterative proportional
fitting), forbidding impossible loops such as battery-discharge →
battery-charge. Read the ribbons as a best-effort attribution, not as metered
truth.

### Relationship to the official Energy dashboard

Home Assistant's Energy dashboard has a sankey-style *Energy distribution* card,
but its nodes are fixed to **solar / grid / battery / home**. For comparison you
can configure it as follows:

| Slot | Suggested entity |
|---|---|
| Solar | `sensor.<dev>_system_pv_energy_today` |
| Grid consumption | `sensor.<dev>_grid_on_energy_in_total` |
| Return to grid | `sensor.<dev>_grid_on_energy_out_total` |
| Battery charge | `sensor.<dev>_battery_charge_energy_today` |
| Battery discharge | `sensor.<dev>_battery_discharge_energy_today` |

> **Prefer the `*_total` cumulative sensors** (`grid_on_*` / `inv_*` with `etin` /
> `etout`). The `*_today` sensors reset every day, and Home Assistant reads a
> cross-day drop **after a long outage** as a device reset, losing the deltas in
> between. Cumulative sensors do not have that problem.

The device-specific **EPS / smart plug / off-grid** ports do not fit the official
model — that is what this card is for.
