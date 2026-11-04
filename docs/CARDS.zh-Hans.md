# 卡片参数总表

`hoymiles` 集成捆绑的八张 Lovelace 卡片的完整参数说明。

[English](CARDS.md) · **简体中文**

---

## 卡片如何加载

集成启动时会把卡片注册为前端模块，因此**无需手动添加资源**，也不依赖任何
CDN。用 **添加卡片 → 手动** 粘贴 YAML，或直接写进仪表盘 YAML 文件即可。

集成安装完并重启 Home Assistant 之后，卡片类型为 `custom:hoymiles-*`。

实际只注入一个模块 `hoymiles-boot.js`，它用静态 `import` 依次引入引导模块、侧栏面板
和八张卡片。这样求值顺序才是固定的 —— `add_extra_js_url` 内部用 set 存 URL，
逐个注册文件时顺序是随机的。

> 改过卡片文件？请硬刷新浏览器（`Ctrl` + `F5`）。

---

## 侧栏面板

添加集成时还会为每个设备注册一个 `panel_custom` 页面，所以**完全不用自己搭仪表盘**。
它以原始 `dev_id` 出现在左侧工作栏，路径 `/hoymiles-<dev_id>`。

| 页签 | 组合的卡片 |
|---|---|
| **系统** | `hoymiles-power-flow`、三个 `hoymiles-gauge`（今日发电 / 充电 / 放电）、`hoymiles-history-chart`（光伏、电池、电网功率，按日）、`hoymiles-energy-sankey` |
| **设备** | `hoymiles-battery`、`hoymiles-pack-list`，外加一张诊断表（型号、固件、序列号、电池电压 / 温度、电网电压、信号强度） |
| **控制** | `hoymiles-control`、`hoymiles-tou-editor` |

几点值得知道：

- **它是组合，不是第二套实现。** 面板里每个控件都是下面那八张卡片之一，只是替你配好了
  设备。想换布局就自己用卡片搭。
- **实体 ID 运行时解析**，不写死：先试常规的 `sensor.<slug(dev_id)>_<key>`，
  再试归一化后缀扫描，最后用集成的 `unique_id`。实体不存在就整块不显示 ——
  没有电网表的设备不会出现一条空的电网曲线。
- **面板内部文字跟随查看用户的界面语言**；侧栏标题不跟随，因为 Home Assistant 在注册时
  就把面板标题固定了 —— 这也是标题直接用 `dev_id` 的原因。
- **只有当前页签的卡片被创建。** 切页签会复用卡片元素，图不会重建、功率流动画不会重播。
- 卡片是命令式创建并缓存的，配置没变就不重新下发。这点很关键：面板每秒都会重渲染
  （1 秒一次的 MQTT 推送），而 `setConfig()` 会清掉卡片内部缓存。

不需要任何配置：配置项加载时自动注册，最后一个使用该设备的配置项卸载时自动移除。

## 通用参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `dev_id` | string | 设备标识 `<client_prefix>-<SN>`（如 `MSA-280520260806`）。除仪表盘卡片（按实体取值）外均为**必填** |
| `language` | `zh` \| `en` | **不填则跟随 Home Assistant**：使用当前登录用户的语言（任何 `zh-*` 都算中文）。只有在需要把某张卡片钉死为某种语言时才填。 |
| `title` | string | 卡片标题，各卡片默认值不同（见下文） |
| `show_title` | bool | 设为 `false` 隐藏标题（部分卡片同时隐藏设备 SN） |

`dev_id` 的作用：卡片据此推导出所需实体 id（`sensor.<dev_id 转下划线>_<后缀>`）。
如果你的实体命名不符合这个规律，用各卡片的 `entities:` 映射单独覆盖。

### 语言是怎么选的

1. 卡片配置里显式写了 `language: en` / `language: zh` → **以它为准**。只有需要把
   某张卡片钉死语言时才写。
2. 否则跟随**当前 Home Assistant 用户**的语言（在 **个人资料 → 语言** 里设置）。
   任何以 `zh` 开头的语言代码（`zh-Hans`、`zh-Hant`、`zh-Hans-CN`）都算中文，
   其余都算英文。
3. 它是在每次渲染时解析的，所以切换个人语言**所有卡片实时跟着变**，不用刷新页面、
   也不用改配置。

> 所以同一个仪表盘对英文用户和中文用户会各自显示成正确的语言：语言是**看的人的属性**，
> 不是卡片的属性。

> `hoymiles-gauge` 是例外 —— 它内部没有任何文案，上面的字全部来自你配置的
> `name` / `label` / `icon`，永远不需要翻译。

### 让自己写的文字也跟随语言

上面的规则只管卡片**内部**的文案。你在 YAML 里写的文字（卡片标题、曲线名、
gauge 的 name、`balancer_label`）是你自己的，卡片无法翻译 —— 但可以在你提供的
多个语言之间选择：把**字符串换成映射**即可。

```yaml
type: custom:hoymiles-history-chart
# 原来： title: History
title:
  en: History
  zh: 历史数据
series:
  - entity: sensor.x_pv_power
    name:
      en: PV power
      zh: 发电功率
```

卡片按解析出的语言（`zh` / `en`）取值。映射里**没有**当前语言时，先回退 `en`，
再回退到任意一个已有的条目，所以残缺的映射也不会变空。普通字符串行为完全不变，
因此**现有仪表盘全都不受影响**。

支持语言映射的参数：

| 卡片 | 支持映射的参数 |
|---|---|
| 所有卡片 | `title` |
| `hoymiles-history-chart` | `title`、`series[].name` |
| `hoymiles-gauge` | `name`、`label` |
| `hoymiles-energy-sankey` | `title`、`balancer_label` |

> 可视化卡片编辑器只能存普通字符串，所以映射在那里显示为**空字段**，标签会写
> `accepts an en/zh map`。这些参数请在 YAML 编辑器（⋮ → *在 YAML 中编辑*）里改。

> Home Assistant 自带的卡片（`markdown`）以及视图 / 页签标题属于 HA 本身、不属于本集成，
> 它们的文字无法跟随语言。请把这些写成语言无关的内容，或者为它们统一选一种语言。

### 为什么视图页签无法跟随语言

HA 从 `view.title` 取页签文字，**完全没有本地化环节**：

```js
// home-assistant/frontend - src/data/lovelace/config/view.ts
computeViewTitle = (view, index) => view.title ?? (view.path ? titleCase(view.path) : String(index));
```

对比 HA 内置的能源面板：它是靠 **strategy** 生成视图、在 JS 里调
`hass.localize(...)` 才让页签跟着语言的。代价是整个视图都由 JS 生成，
只为了一行标签把仪表盘绑上去并不划算。

由此有两件很容易踩错的事：

1. **`view.title` 是固定字符串**，没有按用户变化的语言。想让两种语言的用户都看得对，
   就写成双语 —— 例如 `System status / 系统状态`；或者改用视图内部的语言无关标题
   （emoji + 设备 SN）。
2. **写了 `icon` 就会把标题藏掉**。除非显式要求两者都要，否则 HA 只渲染图标**或**标题：

   ```js
   const icon_and_title = view.show_icon_and_title && view.icon && view.title;
   const icon_only = view.icon && !icon_and_title;
   ```

   所以「有 `icon` 但没有 `show_icon_and_title: true`」的视图**只显示图标**，
   标题只残留在悬停提示里。想同时看到图标和文字就得加这个开关。

---

## 1. `custom:hoymiles-power-flow`

把系统画成一张**接线示意图**（和手机 App 的系统页一致）：每条支路一个图标、
中间是主机（App 那套「方框里插头」的图）、并网点用一个小圆点，连线是粗圆头线
并带流动小球。节点图标直接用 App 的那套图（内嵌在卡片里）。

- **中间的主机只要系统里有任何一路在动就用彩色图**，全系统都 0 W 时才用暗色图。

```
⬜ 光伏1 ──┐                       ┌── ⬜ 光伏2
           ├── ▣ 逆变器 ─── ● ── ── ⬜ 电网
⬜ 微储   ──┘                       └── ⬜ 灯泡
                                     └── ⬜ 智能插座
```

```yaml
type: custom:hoymiles-power-flow
dev_id: MSA-280520260806
title: 我的家
language: zh
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `dev_id` | string | — | **必填** |
| `title` | string | 本地化的「我的家」 | 标题文字 |
| `show_title` | bool | `true` | `false` 隐藏标题与设备 SN，只留右侧信号图标 |
| `language` | `zh` \| `en` | *自动* | 钉死卡片语言；不填则跟随当前 Home Assistant 用户的语言。 |
| `temperature_entity` | entity id | — | 标题右侧显示的温度实体 |
| `show_rssi` | bool | `true` | 右上角 Wi-Fi 信号扇形 |
| `gradient` | bool | `true` | 是否画接线图下的**纯白底**。`false` 则不画，露出卡片自身底色――此时请配浅色主题，因为示意图的文字颜色是固定的 |
| `max_width` | number (px) | `620` | 插图最大宽度，超宽时保持居中 |
| `flow_speed` | number | `1` | 流动珠子速度倍数，`0.5` 更慢、`2` 更快 |
| `variant` | `inverter` | — | 填 `inverter` 改用**微逆画法**（见下）；留空即四支路储能示意图 |
| `image` | URL | HiFlow Pro 2-in-1 产品图 | 微逆画法中间的产品图，需透明底的裁图 |
| `pv_count` | number | *自动* | 微逆画法的光伏输入路数：`1` 画单个 `PV1`，`2` 画 `PV1` + `PV2`。不填则自动判断（见下） |
| `dim_when_idle` | bool | `true` | 微逆画法中全无功率时产品图降为 55% 透明度；`false` 则始终清晰 |
| `entities` | map | — | 实体覆盖，键为后缀（见下） |

### 数据来源

全部来自普通实体状态，**不依赖 recorder**；每条支路都直接取秒级 `quick/state`
的系统实体，与 App 系统页同源：

| 节点 | 实体后缀（`sensor.<dev>_…`） |
|---|---|
| 光伏1（左上） | `sys_pv_p` |
| 光伏2（右上） | `sys_pv2_p` |
| 电网（右） | `sys_grid_p`（正 = 受电） |
| 灯泡（右下） | `sys_load_p` |
| 智能插座（右下，灯泡下方） | `sys_sp_p` |
| 微储（左下） | `sys_bat_p`（负 = 充电），缺失时回退 `bat_p`；SOC 取 `sys_soc` |
| 状态 | `battery_status`（`standby` / `charge` / `discharge` / `lock`） |
| 信号扇形 | `rssi`（dBm） |

### 行为说明

- **有功率（`|P| ≥ 5 W`）的支路用彩色图标，没功率的用同款暗色图标**，
  这就是 App 表达「这里没数据」的方式，不用去读数字。
- 实体**不存在**的支路（从机没有系统级读数）连节点和连线一起省略。
- 电网标题随流向变化：取电显示 `电网输入`、馈网显示 `电网输出`、约 0 W 时
  只写 `电网`——不假装知道方向。
- 连线只有该支路功率 **≥ 5 W** 时才显示流动小球，而且小球**永远顺着能量流动的方向**：
  从光伏1 / 光伏2 流出、从放电的微储流出、从取电的电网流入、流入充电的微储、
  逆变器送电时从逆变器流向汇流点、电网或光伏2 给电池充电时倒流回逆变器，
  以及流入灯泡 / 智能插座。球的颜色随支路变化，速度随功率加快。
- **画面上不画方向箭头**：哪边进哪边出一律由流动小球表示（箭头只是同一件事的第二份
  更粗糙的说明，已按要求去掉）。
- 珠子走完时间**按路径长度算**，所以短线与长线速度一致（最快的支路约 1.5 s 走完，
  最短的短线有 1.0 s 下限，低功率的长线最长 6 s）。觉得还快/还慢就用
  `flow_speed` 整体调。
- **右上角是 RSSI 信号图标**（与「电池卡片」及 App 的 Wi-Fi 图标同款）：
  四根高度递增的信号条，点亮的条数（0~4）表示信号质量，旁边直接跟 `-21 dBm`
  读数，悬停可看说明：

  | RSSI | 点亮条数 |
  |---|---|
  | ≥ −55 dBm | 4（优秀） |
  | ≥ −65 dBm | 3（良好） |
  | ≥ −75 dBm | 2（一般） |
  | < −75 dBm | 1（较弱） |

  设备不上报 `rssi` 时自动隐藏，不需要可以把 `show_rssi` 设为 `false`。
- 单独覆盖某个实体用 `entities:` 段：

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

### 符号约定

`sys_grid_p` **受电为正**，微储功率**充电为负**；卡片在绘制前统一成能直接
理解的语义。没有功率流动的节点只是灰环，不会挂「待机」标签。

### 微逆画法（`variant: inverter`）

HiFlow 是被网微型逆变器，没有电池也没有离网端口，四支路示意图会有一半面积在画
它根本没有的支路。加上 `variant: inverter` 后只画它真实的两端：

```
          ⬜ 并网端口
               │
               └──── ▣ HiFlow Pro 2-in-1
             ⬜ PV1 ────┘
             ⬜ PV2 ────┘
```

即：**产品图居中，并网端口在右上，PV-1 在左下、PV-2 在右下**，与官方 App 的设备
页面一致。三个节点都用正交折线（直角圆角）接到产品图左右边缘，不绕过机身。

```yaml
- type: custom:hoymiles-g2-power-flow
  dev_id: RMI-4161A0209FF6
  variant: inverter
  image: /hoymiles_g2_static/hiflow-pro-2in1.png
  pv_count: 2                 # 一拖二：PV1 + PV2；一拖一填 1
  title: 我的家
  show_title: false
  max_width: 700
```

- **光伏路数由 `pv_count` 决定，缺省自动推断。** 一拖二（HiFlow Pro 2-in-1）有两个
  PV 接口，一拖一（HiFlow）只有一个；画错的后果不是「少一条线」而是**多一个永远
  没读数的节点**。推断顺序：显式 `pv_count` → 有实时 `pv2_power` / `system_pv2_power`
  → 机型名（含 `Pro` 判 2 路、含 `HiFlow` 判 1 路）→ 兜底 1 路。若手里的机型被
  判错，直接写 `pv_count` 即可，不需要改代码。
- **`PV1` / `PV2` 对应设备的 PV 接口**，不是第三方组件。有第三方光伏接入时它会计入
  `system_pv_power` 汇总，但**不会**多出一个 `PV3` 节点——微逆只有两个物理输入口。
- **并网端口显示绝对值**，正文固定为「并网端口」，不随符号改写。方向由**流动珠子**
  和连线颜色表达：`> 0` 取电，珠子朝机组方向流、线为蓝色；`< 0` 馈电，珠子朝电网
  方向流、线为橙色。这样数字好读、方向也不会认错。**并网端口一定会画**，即使读数为
  0 或设备未上报也保留节点（显示 `—`），因为「看不到并网数据」与「并网为 0」是
  两件完全不同的事。
- 中间是产品实拍图（`image` 可换），居中，宽度取 `min(300, 190 × 宽高比)`，宽高比
  按 `image` 文件名从 `IV_PHOTO_ASPECT` 查表（`hiflow.png` = 736/486，
  `hiflow-pro-2in1.png` = 360/168，未登记则按 `360/168`）。两端连线终点距机身左右
  边缘内缩 22 px（`IV_TERMINAL_INSET`），不会压在照片边缘上。
  `image` 也应按机型区分：一拖二用 `hiflow-pro-2in1.png`，一拖一用 `hiflow.png`。
- 画布固定 `700 × 430`，坐标集中在文件顶部 `IV_*` 常量（`IV_NODE_PV1` /
  `IV_NODE_PV2` / `IV_NODE_GRID` / `IV_PHOTO_CX` / `IV_PHOTO_CY` / `IV_CORNER`），
  想微调节点位置改常量即可，不必动绘制逻辑。并网端口的标签画在圆圈**上方**，避免
  压到产品图。
- 全无功率（`|P| < 5 W`）时产品图降为 55% 透明度，用 `dim_when_idle: false` 可关掉。
- 不画电池 / 负载 / 智能插座 / 离网端口——微逆本来就没有这些主题。
- **该选项不自动识别机型**：同一张卡片也用于储能机的 `system` 视图，若靠 `RMI-` 前缀
  自动切换，`system` 视图会被一起改掉。所以只在显式写了 `variant: inverter` 时才切画法。

---

## 2. `custom:hoymiles-battery`

按**实际电池包数量**自适应绘制电池堆：1～4 个电池包各对应一种外形，每个模组
配一个左右交替的气泡显示自己的 SOC 与温度（和 App 的 HiBattery X 页面一致）。
插图按**产品图**绘制：整体一块机身加自顶向下由浅到深的单一渐变、模组之间细缝分隔、
品牌圆标放在第一个模组上；顶部深色头模组画的是**显示条**——电源符号、
「000 W / SOLAR」、两个尖括号夹住的 SOC、「000 W / BATTERY」
（真机显示条上那组小状态图标与 Wi-Fi / 循环符号不上看板，已省略）。
整机画成一个干净矩形：没有侧板，也没有脚。

  - SOLAR / BATTERY 显示的是**本机**的 `pv_power` / `bat_power`（面板画的是设备自身），
    四个角的气泡仍用系统级读数。数值按实际显示（**不补零**），最大到四位（9999 W）。
  - **两个尖括号就是充放电指示**：充电时画左箭头、放电时画右箭头，都是白色；电池待机时两个都不画。
    充电对应电池功率为负，与固件约定一致。

主机温度的气泡也指向这个头模组。

```yaml
type: custom:hoymiles-battery
dev_id: MSA-280520260806
title: HiBattery 4020 X
language: zh
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `dev_id` | string | — | **必填** |
| `title` | string | 自动读设备型号 | 覆盖设备注册表里的型号 |
| `show_title` | bool | `true` | `false` 隐藏标题 |
| `language` | `zh` \| `en` | *自动* | 钉死卡片语言；不填则跟随当前 Home Assistant 用户的语言。 |
| `show_history` | bool | `true` | 可选历史数据区（需启用 recorder） |
| `show_host_temp` | bool | `true` | `false` 隐藏主机温度 |
| `max_width` | number (px) | `560` | 插图最大宽度 |
| `alarm_entity` | entity id | — | 该实体为 `on` 时标题左侧显示铃铛 |
| `entities` | map | — | 实体覆盖（见下表） |

| `entities` 键 | 含义 |
|---|---|
| `pack_count` | 电池包数量 |
| `pv` | 光伏功率 |
| `grid_on` | 并网口功率 |
| `grid_off` | 离网口功率 |
| `battery` | 电池功率 |
| `battery_status` | 电池状态 |
| `soc` | 系统 SOC |
| `pack<N>_soc` | 逐包 SOC |
| `pack<N>_temperature` | 逐包温度 |
| `battery_temperature` | 固件自己算的电池温度（主机温度的兵底） |

### 行为说明

- **标题默认取设备注册表里的型号**（本机实测为 `HiBattery 4020 X`，来源于固件 MQTT
  discovery 的 `device.model`），所以换机型不用改卡片配置；显式写 `title` 则覆盖它。
- 电池数量优先取 `pack_count`（`device/state` 的 `pack_num`），缺失时按实际能读到
  SOC 的 `pack1_soc`…`pack4_soc` 推断，上限 4（与固件 `packs` 截断一致）。
- 逐包数据用 `pack<i>_soc` / `pack<i>_temperature`；四周功率用 `pv_power`、
  `grid_on_power`、`grid_off_power`、`battery_power`。
- **主机温度取已安装电池包的平均值**，画成一个与逐包气泡同款的独立气泡（标注为
  「主机」，样式与 Battery 1/2/3 完全一致）——头部本身没有温度传感器，厂商 App 用的
  也是这个口径。读不到温度的包不参与平均；一个都读不到时回退到固件的
  `battery_temperature`（`bat_temp`）。`show_host_temp: false` 可去掉该气泡。
- 标题右侧的信号格数由 `rssi`（dBm）换算。
- 历史数据区（可选）通过 `recorder/statistics_during_period` 读取长期统计，画 SOC
  曲线并汇总该区间的充电 / 放电电量；recorder 未启用时只提示、不影响其余部分。

---

## 3. `custom:hoymiles-pack-list`

电池堆插图的紧凑替代：一行一个电池包，左侧 SOC 进度条、右侧 SOC 百分比与加热标记。
包数量与电池卡片用同一套规则。

```yaml
type: custom:hoymiles-pack-list
dev_id: MSA-280520260806
language: zh
title: 电池电量
columns: 2
show_temperature: false
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `dev_id` | string | — | **必填** |
| `title` | string | 本地化的「电池电量」 | 标题文字 |
| `language` | `zh` \| `en` | *自动* | 钉死卡片语言；不填则跟随当前 Home Assistant 用户的语言。 |
| `columns` | number | `1` | 按 N 列排布；不填为单列 |
| `show_temperature` | bool | `true` | `false` 时只显示 SOC，不显示 ℃ |

---

## 4. `custom:hoymiles-history-chart`

按**日 / 月 / 年**查看曲线，并可用 `‹` `›` 或日期输入框翻到任意时间段，绘制风格与
厂商 App 的历史页一致。功率 / 电量这类**会相加**的 series 会堆叠（正值向上、负值向下，
因此「充电 / 放电」双极性传感器自然分居 0 线两侧）；而 SOC、温度这类**水平量**默认
**叠加显示**——三个电池包都是 81% 时若堆叠，第二条曲线会被画到 81~162%、第三条到
162~243%，在 0~100 的轴上就只有第一条看得见。用 `stack` 可显式指定。

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

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `series` | list | — | **必填**，每条曲线一项：`entity` / `name` / `color` |
| `dev_id` | string | — | 可选（所有 series 都给了 `entity` 时可省） |
| `title` | string | — | 卡片标题 |
| `language` | `zh` \| `en` | *自动* | 钉死卡片语言；不填则跟随当前 Home Assistant 用户的语言。 |
| `range` | `day` \| `month` \| `year` | `day` | 初始范围 |
| `height` | number (px) | `330` | SVG 高度 |
| `unit` | string | — | 纵轴单位（超过 1.5 kW 自动换成 kW） |
| `zero_line` | bool | `true` | 是否画 0 线 |
| `symmetric` | bool | `true` | `false` = 从 min 到 max 自底向上（SOC 用） |
| `stack` | bool | 同 `symmetric` | `false` = 各条曲线叠加显示而不堆叠；**水平量（SOC、温度）不要堆叠**，只有会相加的量（功率、电量）才堆叠 |
| `min` / `max` | number | — | 固定上下限 |
| `span` | number | — | 对称模式下固定半量程 |
| `sync_group` | string | — | 同一组的卡片共享时间窗口（范围 + 日期） |
| `show_toolbar` | bool | `true` | `false` 隐藏本卡的时间控件（给跟随卡用） |

### 行为说明

- 数据来自 `recorder/statistics_during_period`（长期统计），**无需管理员权限**，
  也不接触数据库文件。
- 顶栏与厂商 App 的历史页一致：**左上角是日期胶囊（圆形 `‹` `›` 包着日期），
  右上角是范围下拉（日 / 月 / 年）**；曲线下方的图例也是 App 那种圆角胶囊。
- 纵轴刻度会按实际步长自动决定小数位（例如 1.25 kW 的步长会显示 `1.25` 而不是取整成 `1`）。
- 固定 `span` / `min` / `max` 可让同一组曲线在不同日子保持同一量程，便于横向对比。
- **点击下方图例可以高亮某条曲线**：选中的曲线加粗提亮，其余曲线淡入背景；
  再点同一条、或点图表区域即取消高亮。悬停浮窗里被淡化的曲线会同步降低透明度。
- **鼠标移到图上时，同一 `sync_group` 的其它图表会在同一时间点显示引导线和浮窗**
  （如仪表盘的「历史数据」驱动「电池容量(SOC)」）；移开后一并消失。匹配按
  时间戳进行，所以两张图即使分桶粒度或数据缺口不同也能对上。
- `show_toolbar: false` 配合 `sync_group` 就能做成「上面一张图控制、下面几张图只跟随」
  的仪表盘。
- 卡片被移除时会自动从组里注销，不会残留。

---

## 5. `custom:hoymiles-gauge`

一张**统计卡**：左上标题、右上图标、中间大字数值，下方**一条绿弧**按数值占
`min`~`max` 的百分比填充，弧中央同时显示该百分比。HA 自带 `gauge` 卡片的轻量替代。

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

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `entity` | entity id | — | **必填**，驱动大字数值 |
| `name` | string | 实体名 | 标题 |
| `unit` | string | 实体单位 | 显示单位 |
| `scale` | number | `1` | 显示前的换算系数（`0.001` 可把 Wh 显示成 kWh） |
| `max` | number | — | **显示单位下的**上限；不填表示弧线随数值增长 |
| `min` | number | `0` | 下限 |
| `decimals` | number | `2` | 数值小数位 |
| `icon` | string | — | 标题右侧的图标 |
| `label` | string | — | 百分比下方的说明文字 |
| `color` | CSS 颜色 | `#22c55e` | 弧线颜色 |
| `show_arc` | bool | `true` | `false` 时去掉弧线与百分比，只剩读数 |

### 比例模式

当真正关心的数字是**两个实体之间的比例**（而不是占某个虚构上限的百分比）时，
可以单独给弧线指定数据源。大字读数仍取 `entity`，只有弧线与百分比来自比例。

| 参数 | 说明 |
|---|---|
| `percent_numerator` | 比例模式必填 |
| `percent_subtract` | 可选，从被减数中扣除 |
| `percent_denominator` | 可选，默认等于被减数 |

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

即：自发自用率 = （发电量 − 上网电量）÷ 发电量。

### 行为说明

- 百分比 = `(值 − min) / (max − min) × 100`，四舍五入到整数；值超出量程时钳到 0~100%。
- 实体还没上报数据时仍画出空弧，数值与百分比显示 `—`，卡片不会变成一片空白。
- 把 `max` 设为 100 并直接接 SOC 传感器，就是一张电池电量表。

---

## 6. `custom:hoymiles-control`

把《禾迈微储 MQTT 协议开发指南》§10~§20 里**所有可下发的控制**做成按钮 / 输入框。
指令**直接发布到协议 topic**（qos 1、retain false），因此即使某个 discovery 实体缺失
或选项列表比协议窄，卡片也仍可用；当前值则从对应实体回读。

```yaml
type: custom:hoymiles-control
dev_id: MSA-280520260806
language: zh
title: 设备控制
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `dev_id` | string | — | **必填** |
| `title` | string | 本地化的「设备控制」 | 卡片标题 |
| `language` | `zh` \| `en` | *自动* | 钉死卡片语言；不填则跟随当前 Home Assistant 用户的语言。 |
| `show_power_ctrl` | bool | `true` | `false` 隐藏「功率控制」行 |
| `show_phase` | bool | `true` | `false` 隐藏「多相输出功率」行 |
| `show_log` | bool | `true` | `false` 隐藏「MQTT 日志」行（日志本身默认是关的） |
| `show_topics` | bool | `false` | 在每行下方显示 MQTT 主题（调试用） |
| `subtitle` | bool | `true` | `false` 隐藏标题右侧的灰色说明 |

### 各行与协议 topic

| 行 | 协议 topic | 说明 |
|---|---|---|
| 设备开关 | `switch/<dev_id>/set` | `ON` / `OFF` |
| EMS 模式 | `select/<dev_id>/ems_mode/command` | `general` / `mqtt_ctrl` / `tou_plan`，不支持的选项自动置灰 |
| 功率控制 | `number/<dev_id>/power_ctrl/set` | 仅 `mqtt_ctrl` 模式有效；它是**租约**：约 60 秒后设备会自动丢弃并回落到 `output_power`。要用「定时下发」行维持。 |
| 定时下发 | 由集成每 N 秒重复下发 `number/<dev_id>/power_ctrl/set` | 默认关闭。打开后按周期（卡片里 5–60 秒，默认 30 秒）重复下发当前功率控制值，使租约始终有效。**下发在 Home Assistant 里执行，不在浏览器里**——切到别的页面、刷新、关闭标签页甚至关掉浏览器都不影响。卡片只是这个后台保活的遥控器，状态从 `sensor.<dev_id>_power_control_keep_alive` 实体读回。关闭开关、或 EMS 模式离开 `mqtt_ctrl` 时自动停止；连续 5 次下发失败也会自动停止并记录错误。非 `mqtt_ctrl` 模式下不可操作。**周期上限 60 秒由卡片强制，后端服务仍接受 5–3600 秒**，这样已有自动化不受影响。 |
| 输出功率 | `number/<dev_id>/output_power/set` | 满载输出上限（W） |
| 多相输出功率 | `number/<dev_id>/phase_output_power/set` | 按 `{"phase_a":..,"phase_b":..,"phase_c":..}` 下发 |
| 获取 TOU 计划 | `sensor/<dev_id>/tou_plan/get` | 应答发布在 `tou_plan/status` |
| 重启设备 | `button/<dev_id>/reboot/trigger` | 二次确认后发 `RESTART` |
| MQTT 日志 | （不发送，只是订阅） | 默认关闭；打开后实时显示设备上报与 HA 下发的数据，保留消息单独标注 |

### MQTT 日志

「计划与维护」最后一行是 **MQTT 日志**，**默认关闭**。打开后卡片会通过 Home Assistant 的
WebSocket（`mqtt/subscribe` 命令）订阅两个通配主题，把两个方向的数据混在一条时间线上显示：

| 通配主题 | 内容 |
|---|---|
| `homeassistant/+/<dev_id>/#` | 设备上报的状态（`quick/state` 1 秒、`device/state`、`system/state`、`tou_plan/status`、discovery 配置）+ HA 下发的命令（`set`/`command`/`trigger`/`get`） |
| `hoymiles/<dev_id>/#` | 集成自己的主题（`availability` 在线看护、`ems_mode/state` 回显） |

- 方向按主题判定：**HA 写命令侧**（`/set`、`/command`、`/trigger`、`/get`）记作
  「HA 下发」，其余记作「设备上报」；`hoymiles/` 那一族是集成自己的，也算下发。
- **服务端补发的缓存消息会被标注。** MQTT 的保留（retain）消息由 broker 存着，任何
  订阅者一连上就立刻收到一份——设备离线一个月也会「收到」。早期版本给它盖了收到的
  时间戳，于是打开日志总看到「刚刚」，误以为离线设备还在上报。现在这类行的时间列显示
  `—`，方向胶囊换成灰色的斜体「缓存（非实时）」（带悬停说明）。**是标注、不是丢弃**：
  `attributes` 能力清单只以保留消息的形式存在，过滤掉会让日志出现大片空白 payload。
- 每行显示时间、方向胶囊、去掉样板后的主题（如 `sensor/quick/state`，完整 topic 在悬停提示里）
  和 payload；payload 是 JSON 就自动缩进，过长则截断。
- 列表**只保留最近 200 条**（`quick/state` 每秒一条，约 3 分钟），丢弃的旧条数会计数显示。
- 关闭时**不订阅任何主题**（不看就不占资源）；离开页面会退订，回到页面时若还开着会自动恢复。
- 🔴 `mqtt/subscribe` 在 Home Assistant 里**仅管理员可用**，所以非管理员账号打开时会看到
  一行提示而不是数据流。

### 行为说明

- 卡片的范围提示（如 `-1000 ~ 1000 W`）优先读实体的 `min` / `max` 属性，
  读不到时用协议默认值。
- **同一设备有多个 `number` 实体时，优先用 `entities:` 钉住；不钉也能自动认对了。**
  `power_ctrl` 与 `output_power` 是两个平级的 `number` 实体，都可能落在
  `number.<dev>` 与 `number.<dev>_2` 上，而**哪个是哪个随固件而变**：实测 FF6（一拖二）
  是 `_2` = `power_ctrl`，FC22（一拖一）正好相反，储能机又是 base = `power_ctrl`。
  所以后缀顺序**不可靠**。真正稳定的是**实体自己声明的范围**：固件给 `power_ctrl`
  的下限在 0 或以下（可限到 0，储能机还能负到充电/馈电），而 `output_power` 的下限
  是硬件最小输出，实测各机型都是 100 W。卡片因此**先按 `min` 判断**
  （`min <= 0` → `power_ctrl`，`min > 0` → `output_power`），只有在候选不唯一时才
  退回后缀顺序，而 `entities:` 里的显式指定永远最优先。若两行显示的范围明显不对
  （例如「输出功率」显示成 `0~132`），就是这一条没配上，请显式钉住。
- **「设备开关」只显示「上次下发」，不假装知道开关状态。** 固件确实发布了一个
  `state_topic`，但内容是嵌套的 JSON 文档（`device/state`），永远不可能等于 `ON` /
  `OFF`，集成因此在发现自己配置里刻意去掉了这个主题（`discovery_override.py` 的
  `_patch_switch`），实体变为乐观模式。后果是：**它显示的 `ON` / `OFF` 是 Home
  Assistant 自己的记忆，不是设备的回答**——重启后回到 `unknown`，也没法通过它判断
  设备是否真在运行。卡片因此改写成「上次下发：开机 / 关机（设备不上报开关状态）」
  或「尚未下发指令——设备不上报开关状态。」，要看设备是否在运行请用 `device` 视图的
  功率流卡片和别的只读传感器：**光伏功率非零就说明设备醒着并在发电，哪怕开关那一行
  写着关机**。（早期版本这里有一行「设备回读」，已经移除：同样的数字在
  `device` 视图的功率流卡片里更大更清楚，放在控制页里只是重复。）
- **卡片会记住本机上一次下发的值，刷新页面不用重新拨一遍。** 上面说过，`power_ctrl`、
  `output_power` 和电源开关都没有可用的状态主题，实体读回来是 `unknown`——如果只靠
  实体回填，每次打开 `control` 视图都是空白滑块 + 默认周期，用户必须重新开机、重新
  调功率、重新填周期，这完全不可接受。所以卡片额外把**本机最后一次下发的值**写进
  浏览器 `localStorage`，键是 `hoymiles-g2-control:<dev_id>`：

  ```json
  { "switch": "on", "ems_mode": "power_ctrl", "power_ctrl": 200,
    "output_power": 300, "timer_period": 45, "at": 1793774422400 }
  ```

  只在用户**真正下发**时写入（点开关机写 `switch`、点下发写对应字段、设周期写
  `timer_period`），不做后台轮询式保存。回填优先级从高到低是：
  **① keep-alive 运行中的持有功率**（集成侧服务端真值，会覆盖浏览器记忆并同时回写）
  → **② HA 实体当前值**（仅当不是 `unknown` / `unavailable`）
  → **③ `localStorage` 记忆值** → **④ `power_ctrl` 退化取 `output_power`**。
  记忆值只用于**回填界面**，绝不会在打开页面时自动重发，不会产生 MQTT 流量。
  两点限制：记忆按**浏览器**存（换浏览器、无痕窗口、清站点数据后丢失，属预期行为）；
  定时下发周期只在心跳**实际运行中**才采信传感器上报的 `period`，空闲时传感器的
  `period` 是内置默认值，照单全收会静默覆盖用户此前选的周期。

- 布局参考 iOS 设置页：小组件包在圆角分组里、组间有灰色小节标题
  （**电源与模式 / 功率设置 / 计划与维护**）、每行是「图标 + 名称 + 右侧控件」，
  分割线**左侧内缩**；开关机与 EMS 模式用**分段控件**，危险操作（重启）用红色。
- **输入框空着就是空着，不会被当成 0。** `Number("")` 在 JavaScript 里是 `0`，而
  `Number.isFinite(0)` 又是 `true`，所以早期版本把一个清空或从没填过的输入框渲染成
  `0`，看起来就像一个真的值，一旦误点下发就会发出 `output_power = 0`——设备很听话地
  停止发电。现在空值在**转成数字之前**就被识别：数字框真的留空并显示灰色提示「未设置」，
  滑块停在范围下限（那只是个画法，不会被当成用户的值）；`_draftNumber()` 对空串、纯空格
  一律返回 `null`，所有下发路径（功率控制 / 输出功率 / 多相输出 / 开启定时下发）遇到 `null`
  只弹一句「数值无效」而不发布任何东西。
- **开关机很慢**：固件要把 PCS（及电池包）真正停下来或启动起来。卡片会把请求状态
  显示为「待确认」最多 5 秒，直到设备回读到位，随后短暂显示对勾。
- 每行的 MQTT topic **默认不显示**（它们是调试信息，会挤掉正文）；需要时用
  `show_topics: true` 打开。
- **MQTT 日志**：见上一节。它默认关闭，开关就在「计划与维护」那一行；`show_log: false`
  可以把整行去掉。
- **「定时下发」打开后不再刷文字。** 以前开启时副标题会写「每 30 秒下发一次 · 已下发 12 次
  · 上次 10:04:11」，每秒随状态推送重写一遍，既抖动又推高行高（曾经挤掉副标题让整行
  看着像空的）。现在开启时这一行什么也不说——分段控件已经显示「开启」、输入框已经显示
  周期，再写一遍只是噪声。只有两种情况保留文字：未就绪（需先切到 `mqtt_ctrl`）和失败
  （把集成侧的错误译成一句可操作的话）。
- **「定时下发」不是浏览器定时器。** 早期版本在卡片里挂了一个 `setTimeout`，只要离开面板
  就失效：元素被移出 DOM，定时器随之消亡，设备一分钟后回落到 `output_power`，而界面上
  没有任何提示。现在这个心跳放在集成里（`keepalive.py`），关掉面板也会继续跑，卡片只负责
  遥控和回显。两个后果值得知道：两个浏览器不会互相打架（每台设备只有一个心跳），
  刷新后这一行也是诚实的（它读实体的属性，而不是本地标志位）。
- **「定时下发」的周期上限是 60 秒，卡片强制。** 输入框写 `min=5 max=60`，超过 60
  或者写成 0 / 负数 / 无法解析的内容都会被钳制：`120 → 60`、`9999 → 60`、空 → 30、
  `0 → 30`，并且**会把钳制后的值写回输入框**——否则输入 120 后框里还留着 120，而实际
  只用 60，看起来就像上限没生效。**后端服务仍接受 5–3600 秒**（`services.py` 的
  `vol.Range(min=5,max=3600)`），这是刻意的：已有的自动化可以继续用长周期，上限只在
  这个卡片界面上执行。
- **EMS 那一行写着 `mqtt_ctrl`，却提示「需先切到 mqtt_ctrl」**：这是可能的。select 的
  状态主题是 retained 值，固件按自己的慢节奏刷新，可能与设备**实际**所处的模式不一致。
  保活相信设备**上报**的模式（不一致时拒绝下发，因为其他模式下设备根本不理会
  `power_ctrl`），错误文本里写的也是设备实际报告的模式。实测 FF6 在切到 `mqtt_ctrl` 后
  设备仍连续两次自报 `general`，此时下发 `power_ctrl` 设备毫无反应。排查时请只看
  `sensor.<dev_id>_ems_mode_device`（来自设备自报的 `device/state`），不要看
  `select.ems_mode`——后者是集成的回显。

---

## 7. `custom:hoymiles-tou-editor`

分时计划可视化编辑器。它通过集成服务（`hoymiles.set_tou_day_plan`、
`set_tou_week_plan`、`get_tou_plan`、`set_ems_mode`）与设备交互；万一集成不在了，
会退化为直接 `mqtt.publish`。

```yaml
type: custom:hoymiles-tou-editor
dev_id: MSA-280520260806
language: zh
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `dev_id` | string | — | **必填** |
| `title` | string | 本地化的标题 | 卡片标题 |
| `language` | `zh` \| `en` | *自动* | 钉死卡片语言；不填则跟随当前 Home Assistant 用户的语言。 |
| `require_tou_mode` | bool | `true` | 只有在 EMS 模式为 `tou_plan` 时才渲染编辑界面；`false` 关掉该门控 |
| `ems_entity` | entity id | 自动 | 覆盖用于读取 EMS 模式的实体 |
| `status_entity` | entity id | 自动 | 覆盖用于读取计划状态的实体 |
| `day_ack_entity` | entity id | 自动 | 覆盖日计划应答实体 |
| `week_ack_entity` | entity id | 自动 | 覆盖周计划应答实体 |

### 行为说明

- 一天由若干时间段（segment）组成，字段为 `mode` / `ts` / `te` / `sh` / `sl` /
  `pc` / `pd`；`ts`、`te` 是 15 分钟为单位的槽位（`0`~`96`）。
- 模式：`1` 强制充电、`2` 光伏充电、`4` 放电。
- 卡片会依次下发 `day1`…`day8` 日计划 → 周计划 → 切到 `tou_plan` → 回读当天计划。
- 卡片自带 UI 配置编辑器，也可以在仪表盘里图形化添加与配置。

> **为什么要有 EMS 门控。** 早期固件没有给 `ems_mode` 提供 `state_topic`，集成会给它
> 补一个**自维护的 retained 状态话题** `hoymiles/<dev_id>/ems_mode/state`：
>
> - 任何人向 `…/ems_mode/command` 下发后，集成立即回显到该话题 → 界面 / 卡片即时刷新；
> - 同时跟随 `system/state` 里的 `ems_mode`（设备真实运行模式，5 分钟周期）进行纠正，
>   所以设备侧超时自动回退到 `general` 也能反映出来。
>
> 为什么不直接把 `state_topic` 指向 `system/state`：该话题只有 5 分钟周期，而本卡片
> 是用 select 状态做门控的，那样会让「切到 tou_plan」后最多卡 5 分钟。

---

## 8. `custom:hoymiles-energy-sankey`

基于长期统计绘制的「源 → 汇」能量流桑基图。

```yaml
type: custom:hoymiles-energy-sankey
dev_id: MSA-280520260806
title: 能量流
language: zh
range: today
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `dev_id` | string | — | **必填** |
| `title` | string | 本地化标题 | 卡片标题 |
| `language` | `zh` \| `en` | *自动* | 钉死卡片语言；不填则跟随当前 Home Assistant 用户的语言。 |
| `range` | `today` \| `7d` \| `30d` \| `month` | `today` | 时间范围 |
| `balancer_label` | string | 本地化 | 「损耗 / 未计量」节点的自定义名称 |
| `show_toolbar` | bool | `true` | `false` 隐藏时间段切换栏 |
| `ribbon_gap` | number (px) | `3` | 带宽之间的白色间隙 |
| `ribbon_opacity` | number | `0.5` | 带宽透明度（0~1） |
| `icons` | map | — | 逐节点 emoji 覆盖，如 `pv: "☀️"` |
| `statistics` | string \| list \| map | — | 覆盖默认 `statistic_id`。值可以是单个 id 或数组，数组会被求和 |

### 数据来源

卡片调用 HA 官方的 WebSocket 统计接口读取**长期统计**：

```
recorder/statistics_during_period
  statistic_ids: [...]   # 本设备的能量传感器
  period: "day"
  units: {energy: "kWh"} # 由服务端换算单位
  types: ["change"]      # HA 已算好的区间增量
```

因此：

- **不接触** recorder 数据库文件（不读 SQLite、不受 schema 迁移影响）
- **不需要管理员权限**（`statistics_during_period` 没有 `require_admin`）
- 只依赖 recorder 集成（属于 `default_config`）
- 渲染是自绘 SVG，**不依赖 CDN**，离线也能用

### 交互

点击某条带可以把这条流单独高亮；点击某个节点方框可以高亮所有与它相连的带。
其余部分变暗，并在详情面板列出涉及的流。再点同一目标（或点空白处）取消高亮。
这只是视图状态，数值不会改变。

### 关于「损耗 / 未计量」节点

桑基图要求流量守恒，而设备各端口是**独立计量**的（转换损耗、采样相位、
未计量负载都会造成差额）。卡片**不做归一化缩放**，而是把差额显式画成一个
节点（正差额记为「损耗/其他」，负差额记为「未计量」），
保证图面守恒且各条数值真实。

### 渲染精度说明

两侧各是一列节点方框。由于设备每个端口独立计量，带宽背后的**走线并非实测**：
它是在禁止「电池放电 → 电池充电」这类不可能环路的前提下，用迭代比例拟合
把每个源按比例分摊到各个汇上得到的估计值。请把带宽当作尽力而为的归因，
而不是计量事实。

### 与官方能源仪表盘的关系

HA 自带能源仪表盘有 Sankey 风格的「能量分布」卡片，但节点固定为
**光伏 / 电网 / 电池 / 家庭** 四类。配置方法：

| 位置 | 建议实体 |
|---|---|
| 太阳能 | `sensor.<dev>_system_pv_energy_today` |
| 电网受电 | `sensor.<dev>_grid_on_energy_in_total` |
| 电网送电 | `sensor.<dev>_grid_on_energy_out_total` |
| 电池充电 | `sensor.<dev>_battery_charge_energy_today` |
| 电池放电 | `sensor.<dev>_battery_discharge_energy_today` |

> **优先用 `*_total` 累计口径**（`grid_on_*` / `inv_*` 的 `etin` / `etout`）。
> `*_today` 型每天清零，HA 在**长时间停机后**会把「跨天下降」识别为设备重置，
> 中间天数的增量会丢失；累计型没有这个问题。

设备特有的 **EPS / 插座 / 离网** 端口官方模型装不下，那部分用本卡片展示。
