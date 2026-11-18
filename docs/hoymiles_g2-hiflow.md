# HiFlow (RMI) 微逆支持 — `hoymiles_g2`

本文说明 `hoymiles_g2` 集成如何支持 **RMI 前缀的 HiFlow 微型逆变器**（微逆），以及这些行为背后的 MQTT 协议事实。

> **源码位置**：集成源码就在本仓库的 [`_g2src/hoymiles_g2/`](../_g2src/hoymiles_g2/)，部署到 HA 的 `/config/custom_components/hoymiles_g2/`。请直接改源码后用 `scripts/deploy-g2.ps1` 部署，**不要再打补丁**。
>
> 同目录的 `hoymiles_g2-hiflow.patch` 是最早期的历史产物（当时源码还没纳入本仓库），仅作存档，**已不再适用、不要应用**。它以 `hoymiles` 目录为基准，和现在的 `_g2src/` 结构早已对不上。

## 改动概览

### 协议与实体

| 文件 | 改动 |
| --- | --- |
| `const.py` | 产品识别码（PID）相关：`PID_PV_COUNT`（`1650`→1、`4160`→1、`4161`→2、`4162`→4）、`INVERTER_PIDS` / `STORAGE_PIDS` / `KNOWN_PIDS`、`serial_body()` / `serial_pid()` / `is_inverter_dev_id()` / `pv_count_from_dev_id()` / `model_from_dev_id()`、能力常量 `CAP_*` 与 `CAPABILITIES_ALL`、告警码表 `ALARM_CODES`（英文）+ `ALARM_CODES_ZH`（中文）+ 四元组 `ALARM_CODE_RANGES`、产品图常量 `HIFLOW_*_IMAGE_FILENAME` + `FRONTEND_IMAGES` |
| `mqtt_util.py` | `async_discover_dev_ids()` 按 PID 过滤发现主题（不看前缀），返回带前缀的完整 `dev_id` |
| `config_flow.py` | 以 PID 而非前缀校验输入（`dev_id_invalid`） |
| `coordinator.py` | `capabilities` / `has_capability()` / `capabilities_known`、三级推导的 `pv_count`、`_ems_mode_value()` 双源读取、`set_keepalive_state()` |
| `sensor.py` | 逐口实体按 `pv_port` 门控、`requires_absent` 反向门控、`pv()` 优先读 1 秒 `quick/state` 的 `pv<n>_p`（兼容 `pPv<n>`）、`grid_port()` 优先读 1 秒 `grid_on_p`（兼容 `pAc`）、`pv_energy*` 从 `pvs[]` 求和、`HoymilesAlarmSensor` 与告警解码、`_async_prune_stale_entities()` 清理过时实体 |
| `discovery_override.py` | `on_object` 回调上报 `phase_output_power` 能力 |
| `number.py` / `binary_sensor.py` / `services.py` | 功率控制、keep-alive 服务与相关实体 |

### 仪表盘与卡片

| 文件 | 改动 |
| --- | --- |
| `lovelace.py` | 自动生成三视图仪表盘（System / Device / Control）、`_LAYOUT_KEY` 版本化布局 `_LAYOUT_VERSION = 22` 与逐版迁移链、`_alarm_entity_id()` / `_resolve_entity()` 按 `unique_id` 解析实体、并排布局常量 `_FLOW_COLUMNS = 24` / `_ALARM_COLUMNS = 24` / `_SECTION_COLUMNS = 48` / `_DEVICE_FLOW_MAX_WIDTH = 0`（0 = 不设像素上限，占整行时由卡片钉在半行宽度）、可选曲线卡片的增删（`OPTIONAL_CHARTS` / `async_get_optional_charts()` / `async_set_optional_charts()`）、device 视图里的「更多数据」开关卡片（`CHART_OPTIONS_CARD`） |
| `options_flow.py` | 选项菜单新增「可选的设备曲线卡片」步骤（`async_step_charts`），按设备 dashboard 现状预选勾选框 |
| `www/hoymiles-g2-alarm.js` | 告警卡片：列表渲染（名称**中英双语**，按界面语言决定主次）、四种状态分支（不可用 / 尚未收到 / 无告警 / 有告警）、`only_when_alarm`（无告警时整卡隐藏且 `getCardSize()` 返回 0，把行让给旁边的功率流图） |
| `www/hoymiles-g2-battery.js` | 微逆模式：设备识别、`_isMicroInverter()`、`_microInverterBody()`、样式 |
| `www/hoymiles-g2-power-flow.js` | 微逆布局 `variant: inverter`：只画光伏 + 并网端口，中间放产品图；`alarm_entity` 在画布左上角画健康徽标（无告警绿圈对勾 / 有告警**实心红三角感叹号**，与厂商 G3 仪表盘一致），并在告警卡隐藏时由 `_syncRowSpan()` 经 `_gridItem()` 找到真正带 `grid-column` 的那层祖先、把它撑成 `1 / -1`（`0` 与「未知」都撑，因为 `only_when_alarm` 两种情况都不显示），同时由 `_wrapStyle()` 把插图钉在半行宽度上、居中，保证两种状态下**卡片高度一致**（宽度变、高度不变）；`max_width: 0` 表示不设像素上限，半行时 `max-width:none`、整行时取实测的半行宽度 |
| `www/hoymiles-g2-history-chart.js` | 单调三次曲线平滑、**左边缘**从 0 线斜坡升起（`baseAt()` 锚点，右边缘不补——窗口右侧还在继续补充数据）、滚轮以光标位置为锚缩放横轴 / 拖动平移 / 双击复位（**仅曲线模式**，柱状图不缩放：30 根柱缩小后只剩四根，比较就没了）、默认从 0 点开始、载入时曲线从 0 线「长出来」（`_playGrow()`，30 秒自动刷新不重放）；`mode`（`auto`/`bar`/`line`）+ `scale` 让月/年电量画成**柱状图**，`show_totals` 在顶部显示「合计」并在图下排出月/年/总发电量三块小卡；`since` **只裁剪数据不缩横轴**；缺失的时间段补成 0（`_filledTimes()`，电量与 `%` 保持前值），且虚线光标指不进去（`holes`） |
| `www/hoymiles-g2-gauge.js` / `hoymiles-g2-history-chart.js` / `hoymiles-g2-energy-sankey.js` / `hoymiles-g2-control.js` / `hoymiles-g2-tou-editor.js` / `hoymiles-g2-pack-list.js` | 各卡片按能力/机型自适应 |

### 产品图

| 文件 | 说明 |
| --- | --- |
| `www/hiflow.png` | 产品图（27087 B，736×486），随卡片一起由集成提供 |
| `www/hiflow-800.png` | HiFlow（型号代码 `1650`）产品图（18178 B，189×168 透明裁切） |
| `www/hiflow-pro-1in1.png` | HiFlow Pro 1-in-1（`4160`）产品图（25252 B，237×168 透明裁切） |
| `www/hiflow-pro-2in1.png` | HiFlow Pro 2-in-1（`4161`）产品图（38150 B，360×168 透明裁切） |
| `www/hiflow-pro-4in1.png` | HiFlow Pro 4-in-1（`4162`）产品图（54518 B，366×168 透明裁切） |

## 部署方式

源码在 [`_g2src/hoymiles_g2/`](../_g2src/hoymiles_g2/)，改动后这样部署：

```powershell
# 一键部署（打包 → scp → 解包 → 重启 core）
powershell -ExecutionPolicy Bypass -File scripts\deploy-g2.ps1
```

手工等价步骤：

```bash
# 本地打包
cd _g2src/hoymiles_g2
tar -czf $env:TEMP\g2.tgz .

# 上传并解包
scp -i <key> -P 22 $env:TEMP\g2.tgz root@<HA-IP>:/config/g2.tgz
ssh -i <key> -p 22 root@<HA-IP> \
  'cd /config/custom_components/hoymiles_g2 && tar -xzf /config/g2.tgz && rm -f /config/g2.tgz'

# 重启
ssh -i <key> -p 22 root@<HA-IP> 'ha core restart'
```

产品图随集成一起下发（`www/hiflow*.png`，由 `const.FRONTEND_IMAGES` 注册为静态路由），无需手工复制。

> 若改了 `www/*.js`，记得删掉可能残留的预压缩副本 —— 旧 `.js.gz` 会被 aiohttp 优先返回，导致改动看不到：
> `rm -f /config/custom_components/hoymiles_g2/www/*.js.gz`

## 卡片行为

### 电池卡片（`hoymiles-g2-battery`）

- `model` 含 `HiFlow`，或 `dev_id` 以 `RMI-` 开头 → 显示产品图 + 光伏输入 / 并网输出 / 今日发电。
- 其他（MSA / `HiBattery`）→ 保持原有电池堆栈示意图，行为不变。
- 可用 `variant: inverter` / `variant: battery` 强制指定，`image:` 覆盖产品图。

### 电网卡片（`hoymiles-g2-power-flow`）

这张卡片有两套画法，**由 `variant` 显式选择，不自动识别机型**：

- 默认（`variant` 留空）→ 四支路储能示意图。`system` 视图一直用这套，**不受影响**。
- `variant: inverter` → 微逆画法：产品图居中，**并网端口在右上**，PV 节点沿下方一行排开、**按机身上的接插件实际位置**接到左右两侧（与官方 App 一致）；没有电池 / 负载 / 智能插座 / 离网端口。

> 之所以不做自动识别：同一张卡片既用于储能机的 `system` 视图，也用于微逆的 `system` 视图（RMI 同样有 `sys_pv_p` / `sys_grid_p`），若靠 `RMI-` 前缀自动切换，`system` 视图也会一起被改掉。

```yaml
# 微逆的 device 视图
- type: custom:hoymiles-g2-power-flow
  dev_id: RMI-4161A0209FF6
  variant: inverter
  # image 留空：按序列号前四位的型号代码自动选图（4161 → hiflow-pro-2in1.png）
  title: 我的家
  show_title: false
  max_width: 0
```

> `max_width: 0` 表示**不设像素上限**：正数仍然当作像素上限，省略则用默认 620 px。Device 视图的流图写的就是 `0`（由 `_DEVICE_FLOW_MAX_WIDTH = 0` 下传）。
>
> 但「不设上限」只在**卡片占半行**时成立：告警卡消失后 `_syncRowSpan()` 会把单元格撑成 `1 / -1`，如果此时仍让 SVG 按 `width:100%` 填满，图会跟着变宽、高度也等比翻倍。所以 `max_width: 0` 且**占满整行**时，`_wrapStyle()` 给的是 `max-width:min(100%, <半行宽度>px)`——图保持半行时的大小、居中，只是卡片变长；高度因此在「有告警 / 无告警」两种状态下完全一致（实测同一张卡：半行 746 px 卡片、整行 1123 px 卡片，**高度都是 405 px**，图宽都是 720 px）。那个「半行宽度」是 `_measureHalfWidth()` **实测**出来的：占整行时把 `grid-column` 临时还原成仪表盘原来的值、同时清掉 `max-width`，同步读一次 `clientWidth` 再复原（只读一次布局，且仅在卡片宽度变化时重测）；卡片刚渲染、周边还没定尺时读到 0 会退到 `requestAnimationFrame` 重试，另有 `ResizeObserver` 盯着卡片宽度，防止把中间态的尺寸记成「半行」。测量落地前的一帧用的是 `50%` 估算。

微逆画法的并网端口：

- 数值取**绝对值**，正文固定为「并网端口」，不随符号改写（避免「绝对值 + 方向字幕」自相矛盾）。
- 方向由**流动珠子**和连线颜色表达：`> 0` 取电，珠子朝机组方向流动、线为 `#4a90d9`；`< 0` 馈电，珠子朝电网方向流动、线为 `#f59e0b`。
- `|P| < 5 W` 时不显示珠子，产品图降为 55% 透明度；`dim_when_idle: false` 可关掉这个变暗效果。
- 光伏节点与储能画法一致：`sys_pv_p` 为负（夜间耗电）时珠子反向。

#### 画布几何

画布固定 `700 × 370`，坐标写死在 `hoymiles-g2-power-flow.js` 的 `IV_*` 常量里：

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `IV_PHOTO_W` / `IV_PHOTO_MAX_H` | 300 / 190 | 产品图的最大宽高，实际宽度取 `min(300, 190 × 宽高比)` |
| `IV_PHOTO_CX` / `IV_PHOTO_CY` | 350 / 130 | 产品图中心 |
| `IV_NODE_ROW_Y` | 275 | PV 节点所在的那一行（一路到四路都排在一行） |
| `IV_NODE_X[1..4]` | `[95]` / `[95, 605]` / `[95, 350, 605]` / `[78, 150, 550, 622]` | 按输入路数决定 PV 节点的横坐标 |
| `IV_NODE_GRID` | (605, 90) | 并网端口右上 |
| `IV_TERMINAL_INSET` | 22 | 连线终点距产品图边缘的内缩量（未登记机型兜底） |
| `IV_SIDE_STAGGER` | 30 | 同一侧面有多路但图未登记接插件时的垂直错开量（兜底） |
| `IV_CORNER` | 10 | 折线圆角半径 |

- 产品图按 `IV_PHOTO_ASPECT` 里登记的宽高比计算包围盒（`hiflow.png` = 736/486，`hiflow-800.png` = 189/168，`hiflow-pro-1in1.png` = 237/168，`hiflow-pro-2in1.png` = 360/168，`hiflow-pro-4in1.png` = 366/168）；未登记的图按 `360/168` 兜底。
- 选图顺序：显式 `image` → `IV_IMAGE_BY_CODE`（按序列号前四位，见下）→ `IV_IMAGE_BY_COUNT`（按解析出的 PV 路数）→ 兜底 `hiflow-pro-2in1.png`。产品图是示意图的一部分而不是装饰（每条连线都停在它的边缘上），所以**必须**让机身输入路数与画出来的节点数一致，一拖四画在二输入机身上会让中间两条竖线看起来断在半空中。
- 连线用 `elbowRoute()` 生成正交折线（`M / V|H / Q / H`），终点落在产品图左右边缘的接插件高度上；节点在机身下方正中时改用 `riserRoute()`（纯 `M / V`）直接顶到底边。
- 接插件高度来自 `IV_TERMINAL_BY_ART`（按产品图文件名登记），不是猜的：一拖二登记 `pvFrac` / `pvRightFrac`（左右各一对），一拖四登记 `pvLeftFracs` / `pvRightFracs`（**左右各两对**），并为并网端口登记 `gridFrac`。有登记就走登记值，没有就用 `IV_TERMINAL_INSET` / `IV_SIDE_STAGGER` 兜底。

#### 一拖四（`4162`）的两个接插件对

`hiflow-pro-4in1.png` 的机身**左右各有两个 MC4 插头对**，四路 PV 依次是「左侧上一对、左侧下一对、右侧上一对、右侧下一对」。`pvCount = 4` 时节点横坐标取 `[78, 150, 550, 622]`，`slotSide()` 以 `pvLeftSlots.length` 决定前两路走左脸、后两路走右脸，`elbowRoute()` 的终点高度分别取两对的**中点**（实测左脸 `0.738/0.774`、`0.807/0.842`，右脸 `0.741/0.780`、`0.818/0.860`，均为图高的比例）。同一侧的两路各接自己那一对插头，不会都指向同一点。

**这张图的连线终点不能落在产品图包围盒的左右边缘。** 它是唯一一张「画得比机身宽很多」的裁切图：366 px 宽里机身轮廓只占 x 77..258，左右各留了一大片透明背景，而背景里那些细的斜向线缆装饰又恰好不经过接插件所在的行（实测第 127 行，整个 0..77 的左边距里只有 x 9–26、36–39 是不透明的）。早期按 `photo.l` / `photo.r`（即 x 0 / 366）收线，四个接插件全都停在离机身 65–90 px 的空白里，看起来就是「线没接上」。

因此 `IV_TERMINAL_BY_ART` 为这张图额外登记了 `pvLeftXFrac: 0.222` / `pvRightXFrac: 0.696`（对应 `photo.l + 0.222 × 300 ≈ 266.6` 与 `photo.l + 0.696 × 300 ≈ 408.8`，都落在实测轮廓 263..411 之内），`ivTerminals()` 也相应允许左右两侧各自给出 x（未登记的图纸仍回落到包围盒边缘）。连线稍微**扎进**机身轮廓即可：`edges` 在 `_unitImage` 之前绘制，而裁切图的透明像素不着色，所以被机身盖住的那一小段正好不可见，看起来就是插在机身上。

#### 单输入机型（`1650` / `4160`）

`IV_PV_COUNT_BY_CODE` 把 `1650` 与 `4160` 都解析成 1 路 PV。两处行为因此不同：

- **文案是 `PV` 而不是 `PV1`。** 只有一路输入时编号没有区分作用，节点自己在 `_inverterNodes()` 里带上 `caption`（`pvCount === 1` 时取 `PV`，否则取 `PV<n>`），绘制层直接用这个字段，所以图和文案不会各说各话。两路以上仍然是 `PV1` / `PV2` … `PV4`，与厂商 App 和固件端口表一致。
- **节点默认在左下，但 `4160` 的插头长在右脸。** `hiflow-800.png`（1650）的 MC4 在左脸约 57% 高处，走默认的左侧节点即可；`hiflow-pro-1in1.png`（4160）则**不是**：它的 AC 线从右上出去（约 27% 高处就在图的右侧边缘），DC 插头低低地挂在右脸约 81–98% 高处。`IV_TERMINAL_BY_ART` 因此为这张图登记了 `pvRightFrac: 0.893`、`pvRightXFrac: 0.8`、`pvSides: ["right"]`。
  - `pvSides` 覆写「左脸默认」的判定（`slotSide()` 第一句就读它）；
  - `IV_NODE_X[1]` 只有一个 `95`，`slotX()` 在判定为 `right` 且原始 x 落在产品图左侧时把节点镜像到 `IV_W - x = 605`，于是圆圈留在右下、连线从右上方拐进右脸，不会横穿整张产品图；
  - 该镜像只对「右脸 + 原本在左」的组合生效，`1650` / `4161` / `4162` 的节点位置与连线一个像素都没动。
- 左侧标签在圆圈下方，并网端口标签在圆圈**上方**（`above: true`），避免压到产品图。
- 并网端口的数值正文用绝对值，方向只由珠子与线色表达（见下）。

型号代码与产品图的对应：

| 型号代码（序列号第 5–8 位） | 机型 | 产品图 |
| --- | --- | --- |
| `1650` | HiFlow | `hiflow-800.png` |
| `4160` | HiFlow Pro 1-in-1 | `hiflow-pro-1in1.png` |
| `4161` | HiFlow Pro 2-in-1 | `hiflow-pro-2in1.png` |
| `4162` | HiFlow Pro 4-in-1 | `hiflow-pro-4in1.png` |

### 历史曲线卡片（`hoymiles-g2-history-chart`）

这张卡片有两种画法，由 `mode` 决定，生成仪表盘时写的是 `mode: auto`：

| `mode` | 范围 | 画法 |
| --- | --- | --- |
| `auto` | `day` | 平滑曲线（单调三次插值，不会像样条那样冲出峰值） |
| `auto` | `month` / `year` | **柱状图**，一天（或一月）一根 |
| `line` / `bar` | 任意 | 强制指定 |

`scale` 是统计值的单位换算（电量传感器以 Wh 记账，`scale: 0.001` 让轴、柱子、浮窗、合计全部说 kWh），`show_totals` 在图上方显示一个「合计」胶囊，并在图下并排排出**本月 / 本年 / 累计**三块小卡。

交互：

- **滚轮以光标位置为锚缩放横轴**，左右拖动平移，双击复位。缩放只作用于**曲线模式**（`_zoomable()` 判断：`!_data.bars`）。柱状图不放缩：一个月 30 根柱子缩小后只剩四根可见，比较就没了，而对比正是这张图存在的理由；提示行（「滚动缩放 · 拖动平移 · 双击复位」）也随之只在曲线模式出现。
- 双击复位**计的是 `mousedown`，不是 `click`/`dblclick`**（`_onDragStart()` 里判定，间距 ≤ 8 px、间隔 ≤ `DOUBLE_CLICK_MS` 350 ms）。原因不是风格偏好：图的 `<svg>` 每次渲染都是**重新生成的整段字符串**（`_untrusted(this._svg())`），所以鼠标按下到抬起之间只要发生过一次 `requestUpdate()`（悬停、缩放、平移都会），指针下面的节点就已经被换掉，浏览器找不到「同一个节点上的两次点击」，于是**一个 `click` 都不发，`dblclick` 自然也没有**。`mousedown` 永远会到。配套约束：`_onDragStart()` / `_onDragEnd()` 只切 `.dragging` 类（`_setChartState()` 直接改 DOM），不触发重渲染——否则会吃掉自己那次 `mouseup` 之后的 `click`；平移结束后 `_dragged` 在下次按下时消费掉，且这次按下不再算双击的前半段；指针离开画布（`_onLeave()`）会清掉计时。`click` 路径仍然保留一份兜底，两条路径都幂等。
- **默认从 0 点开始**，不跟着当前时刻居中。
- **曲线与零线之间始终有斜坡**：填充区的顶边不只是采样点，还会在窗口**左边缘**补一个「高度 = 该系列基线（通常就是 0 线）」的锚点（`baseAt()`）。设备 10:40 才上线时，10:40 之前本来什么都没有，旧实现直接从 0 竖直抬到第一个读数，看上去像故障而不是「还没数据」；补上锚点后曲线从左边缘的 0 缓缓升起，和厂商 App 一样。锚点只在左侧确实空着时添加（`> x0 + 0.5`），本来就贴着窗口左界的序列不会多出重复点；柱状图与堆叠带上层不受影响（上层基线下移的是它下面那条带，不是 0 线）。**右边缘故意不补**：窗口右侧是「当前时刻」，会随时间继续补充数据，把尾巴拉回 0 等于宣称这条序列已经停了，而且每过一段数据就会被重画掉。
- **载入时曲线从 0 线「长出来」**（`_playGrow()` + `.grow` 的 `scaleY` 过渡，520 ms）。`transform-origin` 写的是 0 线在 viewBox 高度里的百分比而不是像素，因为 `transform-box: view-box` 会把像素值一起缩放。动画只在**时间窗口变化**时播放（`_growNext` 在切范围 / 切日期 / 改配置时置位），30 秒的自动刷新不会重放——否则每半分钟整张图就抖一次。这条整体缩放与上面那条「边缘斜坡」是两件事：前者是入场动画，后者是静态几何形状。
- 柱状图与曲线的横轴都按 `_barTimes()` 的等分槽位排布（缺失的日子也占一格），所以光标线始终对齐柱心，缺数据的日子也不会被压掉。
- **缺失的时间段画成 0，而不是被平滑过去**（`_filledTimes()` / `_holdsGaps()`）。“缺失”在 recorder 层是**整行不存在**：`recorder/statistics_during_period` 只有在某个 5 分钟桶里至少存在过一个数值状态时才写一行，实体处于 `unavailable` 时一个数都不贡献，于是那一桶直接没有行（不是 `mean: null`）。所以“桶不存在”本身就等于“设备那段时间没上报”。旧实现直接用“有行的时刻的并集”当采样点，10:30 和 11:35 这两条真实的读数就成了相邻点，`smoothPath()` 于是画一条跨过 65 分钟空洞的三次曲线，填充区一起桥过去——看上去像设备一直在发电。现在 `_filledTimes()` 把缺失的桶按 `bucketMs` 补出来，值由 `_holdsGaps()` 决定：
  - **默认降到 0**：功率、电压、电流、频率、无功这些“瞬时测量”在设备离线时不该有值，画 0 才是“没有数据”，一眼能看出断档；
  - **电量与百分比保持前值**：电量是终身累加量，离线期间发的电仍然记在表里，掉到 0 再爬回来等于画了一次“表底清零”；`%`（SOC）同理，0 % 会被读成“电池空了”。
  两个边界：第一点之前的空缺不补（那时连“前值”都没有，属于未知而不是 0）；只在尾段超过两个桶时才补，否则健康设备那个还在累积的当前桶每 5 分钟就会被画成 0 一次。
- **虚线光标指不进空洞**（`_build()` 返回的 `holes` 数组）。把缺失桶补成 0 是“如实”，但浮窗把一个补出来的 0 说成一次读数就是撒谎——所以 `holes[i]` 为真的桶既不接受悬停（`_hoverPosition()` 两条路径都返回 `null`），也不会被 `_onMove()` 的最近点吸附：指针落进空洞时 `_setHover(-1)`，连同步组的虚线一起清掉。曲线掉到 0 让人看见断电，浮窗则安静。判断“空洞”要求**所有系列**在该桶都没有数据，多系列卡片只要还有一条在报就不算缺。
- **柱状图没有空洞概念**：柱子的“缺失”是高度为 0 的柱子本身，`holes` 在 bar 模式下直接为 `null`。

### 可选曲线卡片：把 `device/state` 剩下的读数也画出来

`device/state`（协议 §25）报的读数比生成的 device 视图画的多。差额部分不再写死进布局，而是做成**按需开启**的卡片。两个入口，改的是同一份东西：

- **设备页里的「更多数据」卡片**（`custom:hoymiles-g2-chart-options`，`www/hoymiles-g2-chart-options.js`）：device 视图最后一节，五条曲线各一个开关，勾完就地生效——不用再翻设置。它调 `get_optional_charts` / `set_optional_charts` 两个服务，与 Options Flow 共用 `async_set_optional_charts()`。
- **设置 → 设备与服务 → hoymiles_g2 → 配置 → 「可选的设备曲线卡片」**（`options_flow.async_step_charts`）。

勾选后集成直接改写该设备的 dashboard，把这些卡片插到 device 视图末尾、**紧挨在开关卡片上方**；取消勾选就删掉那一节。仅限微逆（HiFlow / HiFlow Pro），`is_inverter_dev_id()` 之外的设备会直接 `abort` / 服务报错。

> **卡片不会自动刷新页面，但也通常不需要你手动刷**。实测 2026.7.2：后端写完 dashboard 配置后，已经打开着的 Lovelace 面板会自己把改动捡起来——勾上一条，图当场多一张；取消勾选，图当场消失；整个过程中页面没有 reload。所以卡片写入成功后只显示一句「已保存。若本页未随之更新，请刷新页面。」＋一个「立即刷新」按钮，**兜底**给那些没有自动捡起来的版本或时机（面板读配置的时机并非每个 HA 版本都一致）。
>
> 这里刻意不用自动 `location.reload()`：用户往往还在继续勾后几行，自动刷新会把没勾完的操作打断。（早期版本曾据 HA 源码里 `websocket_lovelace_save_config` 只做 `config.async_save()` 推断「浏览器收不到通知」，实测证明这个推断不成立，故改成上面的说法。）
>
> **记录时刻 = 勾选时刻，不是刷新时刻**。`since` 由后端在 `async_set_optional_charts()` 写入时盖下（`_now_iso()`），与页面何时刷新无关；卡片文案因此写的是「卡片从勾选的那一刻开始记录」。
>
> **勾选时锁的是这张卡片，不是 `scrollTop`**。那次面板重建会把整个视图丢掉重画：一来重画出来的视图 `scrollTop` 是 0，二来后端把新卡片插在开关卡片**上方**，于是开关本身被推下去约一个卡高，而 `scrollTop` 纹丝不动——只锁偏移量，锁住的位置就是错的。真正不该移动的是卡片的**视口偏移** `top - scrollTop`（眼睛读的就是这个数），`_holdScroll()` 因此记下 `off = cardTop - scrollTop` 与 `cardTop`（`getBoundingClientRect().top + scrollTop`，即文档偏移，滚动时不变），随后用 `requestAnimationFrame` 盯 5 秒：
> - 卡片**文档偏移**变了 → 上方插进来一张卡片，按 `scrollTop = newTop - off` **绝对**回写。这里必须绝对而不是增量：把“文档偏移的变化量”加到“当前 `scrollTop`”上，会把浏览器自己已经做过的那点补偿再加一遍，开关实际还是滑了约 220 px（正好一个卡高）。
> - 偏移量掉到 ≤1 px → 重建把滚动清掉了，用记下的 `seenY` 还原。
> - 视口偏移自己变了 → 那是用户滚的，采纳新值、不再干预。
>
> 这段状态放在**模块作用域**而不是元素里——重建换掉的正是这个卡片元素本身，实例字段会跟着一起丢。实测漂移 0 px（592.06 → 592.08）。

`set_optional_charts` 是**整体覆盖写入**：没提交的键一律视为 `False`。这跟 Options Flow 里「省略即保持原值」的语义相反，是有意的——开关卡片每次都提交完整的五个布尔值，若默认沿用当前值，「关掉」这个动作就永远提交不出去。

| 卡片 | 实体（`sensor.<设备>_` 之后的部分） | 单位 | 轴 |
| --- | --- | --- | --- |
| Grid Current / 电网电流 | `grid_on_current` | A | 底部起 |
| Grid Frequency / 电网频率 | `grid_on_frequency` | Hz | 底部起 |
| Active Power / 有功功率 | `grid_on_power_5_min` | W | 由数据决定（可能正负） |
| Reactive Power / 无功功率 | `grid_on_reactive_power` | var | 由数据决定（随功率因数变号） |
| Signal Strength / 信号强度 | `rssi` | dBm | 固定 `min: -100` / `max: 0` |

**不做成卡片的**：

- `grid[]` 里的端口数组本身（是结构，不是一条序列；其中单项已经在上表里）；
- PV 组串编号 `pvs[]`（device 视图的「PV Power by Port」已经按端口画过）；
- 系统当前运行的 EMS 模式 `ems_mode`（枚举量，曲线没有意义）；
- `pack*` 相关的 pack 编号与内容（储能机型的既有布局已覆盖，且本功能仅面向微逆）；
- **电网电压 `grid_on_voltage`**：device 视图从第一个版本起就固定画了「Grid Voltage」曲线，再提供一次会在同一页出现两条一模一样的线。

实现上有三点值得记：

- **实体 ID 靠 `unique_id` 解析，不靠猜**。上表写的是 `sensor` 的 `unique_id` 后缀（`hoymiles_g2_<设备>_<后缀>`），不是拼出来的 `entity_id`：HA 用**显示名**的 slug 生成 `entity_id`，两者只在名称恰好等于 key 时才一致。`grid_on_power_5m` 的名字是「Grid On Power (5 min)」，它的实体其实是 `sensor.<设备>_grid_on_power_5_min`；用户改过名字更是无法预测。早期版本按 key 拼接，`有功功率` 卡片指向一个从未存在的实体，曲线永远是空的。现在统一走 `_resolve_entity()`（按 `unique_id` 查实体注册表，找不到才回退到旧拼法），并且布局迁移 revision 20 会把已存盘的可选卡片重新指向真实实体——用不着重新勾选一遍。
- **仪表板就是唯一真值**。没有额外的 `Store` 记「用户勾了哪些」：`async_get_optional_charts()` 直接从已保存的 dashboard 里读回卡片（用 `g2_optional` 这个键标记，卡片本身忽略未知键），所以勾选框的默认值永远等于用户眼前看到的东西，不会出现「设置里勾着、页面上没有」的错位。`async_set_optional_charts()` 先把所有可选卡片摘掉再按顺序重放，保持开启的卡片原样放回（连 `since` 一起），因此重复执行幂等，用户自己塞进同一节的卡片也不会被删（节里还剩别的卡片时该节保留）。
- **卡片记住启用时刻，但只裁剪数据**。新加的卡片写入 `since`（ISO 8601 UTC），`_since()` 解析它，`_build()` 把 `t + bucketMs <= since` 之外的采样点丢掉，所以启用之前即使 recorder 里有数据也不会补画。**横轴不跟着缩**：`_window()` 仍然是干净的日历窗口（日 = 00:00→24:00），早期版本把窗口也钳到 `since`，结果同一页里可选卡片画 10:06→23:00、固定卡片画 00:00→24:00，两张并排的卡片对“横轴”的理解不一致，同步组的虚线也不再落在同一时刻上——时间就是这么对不上的。
- **往回翻没有下限**。`_shiftRange(-1)`、日期选择器、`_earliestAnchor()`/`_clampAnchor()` 都已删除：早期版本会拦住用户不让翻到启用之前，结果同步组把“昨天”广播下去时，这张卡还停在今天，同一页并排显示两天。导航是**组**的，翻到启用之前就画一张空窗口，如实显示「没有数据」。

### 控制卡片（`hoymiles-g2-control`）会记住上一次下发的值

`power_ctrl` 没有 `state_topic`，`output_power` 也常是 `unknown`，所以这两个 `number` 实体在 HA 里根本读不到值。只靠实体回读，每次打开 `control` 视图都会看到空白的滑块和默认值，用户必须重新拨一遍——这没有意义。

卡片改为把「本机最后一次下发的值」写进浏览器 `localStorage`，键为 `hoymiles-g2-control:<dev_id>`，值是：

```json
{
  "switch": "on",
  "ems_mode": "power_ctrl",
  "power_ctrl": 200,
  "output_power": 300,
  "phase": { "a": 200, "b": 200, "c": 200 },
  "timer_period": 45,
  "at": 1793774422400
}
```

写入时机（只在用户真正下发时写，不做轮询式保存）：

| 操作 | 写入字段 |
| --- | --- |
| 点「开机 / 关机」 | `switch` |
| 选「自发自用 / MQTT 功率控制 / 分时计划」 | `ems_mode` |
| 下发功率控制 | `power_ctrl` |
| 下发输出功率 | `output_power` |
| 下发相功率 | `phase` |
| 设定时下发周期 | `timer_period` |

取值优先级（`_seedInputs()`），从高到低：

1. **keep-alive 正在运行时的持有功率**——这是集成侧的服务端真值，会覆盖浏览器记忆，并在同一时刻回写 `localStorage`。
2. **HA 实体当前值**（仅当它不是 `unknown` / `unavailable`）。
3. **`localStorage` 里记住的值**。
4. 都没有时：`power_ctrl` 退化取 `output_power`（设备默认持有的瓦数），仍无则留空。

两个细节：

- 记忆值只用于**回填输入框和选项**，不会自动重发。打开页面不会产生 MQTT 流量。
- 定时下发的周期只在 keep-alive **实际运行中**才采用传感器上报的 `period`；空闲时传感器的 `period` 是内置默认值，若照单全收会静默覆盖用户此前选的周期。

`localStorage` 是**按浏览器**存的：换浏览器 / 无痕窗口 / 清站点数据后记忆会丢失，这是预期行为，不是 bug。

### `show_tou`：微逆没有分时计划

控制卡片有一个 `show_tou` 选项控制是否显示「分时计划」那一行。缺省时它按卡片自己判断是否显示；微逆没有 `tou_*` 主题，集成在生成仪表盘时显式写入 `show_tou: false`，而 `_migrate_control_cards()` 会把旧仪表盘里的 `show_tou` 补成 `false`，避免留下一个点了只会超时的按钮。

### 按角色隐藏控制分组（rev.17）

卡片新增 `show_ems` 选项（显式控制「EMS 控制」分组），同时所有分组都开始按设备角色过滤：`_role()` 读 `system_role` 实体的状态，把固件偶尔发出的 `servant` 归一化成 `slave`，返回 `"single" | "master" | "slave" | null`。

- `slave` 时隐去 **EMS 控制 / 输出功率 / 功率控制 / 分相（三相） / 分时计划**——这些主题从机根本不会响应（协议 §32 的 `has_meter` / `has_plug` / `has_solar2` 在从机恒 `false`，且从机不发任何 `number` 发现对象），留着一个点了没反应的控件比没有更糟；
- 组内条目全部被隐去时，**整组连标题一起不画**（`_group()` 返回空串），避免出现只有标题的空盒子；
- 角色未知（`null`）时**一个都不隐**：主题到得晚，按「未知即从机」处理会在每次 HA 重启后把主人的控制页短暂清空。

### 维护类按钮：重置蓝牙 PIN（§31）与恢复出厂（§29）

「计划与维护」分组的行序是：计划 / TOU → 重启设备 → **重置蓝牙 PIN 码** → **恢复出厂设置** → MQTT 日志。两个新按钮极其相似——同一套 topic 形状、同一个固定负载、同一批机型——差别全在后果大小：

| 项目 | 重置蓝牙 PIN（§31） | 恢复出厂（§29） |
| --- | --- | --- |
| 下发 topic | `homeassistant/button/<dev_id>/reset_ble_pin_code/trigger` | `homeassistant/button/<dev_id>/factory_reset/trigger` |
| 负载 | 固定 `RESET` | 固定 `RESET` |
| qos / retain | `1` / `false` | `1` / `false` |
| discovery 配置 | `.../reset_ble_pin_code/config`，retain **true**，设备连上 broker 时立即发布 | `.../factory_reset/config`，retain **true**，同样时机发布 |
| 后果 | 仅蓝牙配对 PIN 回到默认值，其它配置保留 | 清掉设备全部配置，**包括 MQTT 前缀** |
| 支持机型 | 协议写明 HiFlow / HiFlow Pro | 同左 |

两个都做了二次确认，但提示文字不同：恢复出厂的提示明确写出“包括 MQTT 前缀”——清掉之后设备会以默认前缀重新连上来，集成里那条配置项就指向了一个不再存在的 `dev_id`，必须重新配网；而重置蓝牙 PIN 只需用手机 App 按默认 PIN 重新配对。

**机型门控**：协议只声明微逆支持这两条命令，微逆的 `supported_topics` 里确实同时带 `factory_reset` 和 `reset_ble_pin_code`（见上文实测清单）。卡片侧对应两个选项 `show_factory_reset` / `show_ble_pin_reset`，不填时**按 PID 自行判断**（`MAINTENANCE_PIDS = 1650 / 4160 / 4161 / 4162`），微储的 `2800` 自然不显示；`lovelace.py` 生成微储 control 卡时还会把这两个键显式写成 `false`，让意图在生成的 JSON 里也可见。这样已有的旧仪表盘不需要任何迁移就行为正确。


## 已知限制

`RMI-1650A028FC22`（固件 `01.03.00`）**会**发布 `quick/state` 与 `device/state`，但内容比储能机（MSA）少得多：

| 主题 | 频率 | 微逆（HiFlow）内容 |
| --- | --- | --- |
| `quick/state` | 1 Hz | 5 个聚合字段：`sys_pv_p` / `sys_plug_p` / `sys_grid_p` / `sys_load_p` / `sys_sp_p`，**外加**逐口 `pv1_p` / `pv2_p` 与并网口 `grid_on_p`（实测） |
| `device/state` | 5 min | 单条 `grid[]`（`type=grid_on`，只有 `v/i/f/p/q`）、`rssi`、`pv_num`、`pvs[{id,p,ed,et}]`、`ems_mode` |
| `attributes` | retained | `supported_topics` 能力清单 |
| `system/state` | — | **从不发布** |
| `alarm/state` | 仅变化时 | 非保留、**只在告警集合发生变化时发布**。详见下节 |
| `tou_*` | — | **从不发布**（无分时计划） |

### `alarm/state` 为什么不常看到

早期文档写它「实测从未出现」，那是个**误判**：该主题**不是 retained**，且只在告警产生/消除时发布一次。因此：

- 用一次性订阅或短窗口抓包，很容易一条都抓不到 —— 这**不能**推断设备不上报告警。
- 设备静默期间订阅 `alarm/state` 长时间收不到消息，是**正常**的。

要确认设备是否上报告警，正确做法有三种：

1. 用通配符订阅整个设备树（`_tools/mqtt_devs.py`），能列出该设备实际出现过的主题，`alarm/state` 会出现在其中。
2. 直接读 HA 实体 `sensor.<...>_active_alarms` 的当前值。
3. 在设备确实有告警时观察。

集成侧的 `HoymilesAlarmSensor` 因此继承 `RestoreEntity`：重启后先恢复上次快照，而不是干等下一个（可能几天都不来的）上报。在收到首份报告前 `native_value` 为 `None`（不是 `0`），卡片据此区分「无告警」与「尚未收到数据」。

`device/state` 里没有 `bat_*` / `soc` / `pack_num` / `packs[]`，因此电池、电池包、分时计划、并网口（`grid_off` / `inv`）相关的实体在微逆上都不存在。

### `pvs[]` 在两种机型上不一样

同一个数组名在储能机与微逆上的字段并不相同，这是移植时最容易踩错的地方：

| 机型 | `pvs[]` 单项字段 | PV 电量来源 |
| --- | --- | --- |
| 储能机（MSA） | `{id, p}` | `system/state` 的 `pv_e` / `pv2_e` |
| 微逆（RMI） | `{id, p, ed, et}` | `pvs[].ed`（今日）/ `pvs[].et`（累计） |

也就是说储能机的 `pvs[]` **不发** `ed` / `et`，而微逆没有 `system/state` 可读，**唯一**的 PV 电量就是 `pvs[]` 里的这两个计数器。

因此 `system_pv_energy_today` 采用双源读取：先取 `system/state` 的 `pv_e`，取不到时回退为 `pvs[].ed` 求和。这样一个实体在两种机型上都有效，仪表盘不必按机型分叉。

此外在「没有 `system/state`」的机型上额外创建三个逐口电量实体：

- `pv_energy_total`：所有端口 `et` 之和（累计电量）
- `pv1_energy_today` / `pv2_energy_today`：各端口 `ed`

它们以 `requires_absent=CAP_SYSTEM_STATE` 门控 —— 即“设备**没有**该主题时才创建”，与储能机的同名电量实体互斥，避免两套传感器同时出现。求和按 `pvs[]` 实际条目数进行，不假定端口数量（HiFlow 通常是 2 口）。

### 实时功率取 1 秒的 `quick/state`，不取 5 分钟的 `device/state`

微逆的 `quick/state`（1 Hz）里带有逐口功率 `pv1_p` / `pv2_p` 和并网口 `grid_on_p`，而 `device/state`（5 分钟）里的 `pvs[].p` / `grid[0].p` 是**同一个数值**，只是慢 300 倍。

因此实体取值一律**优先**读 `quick/state`，读不到才回退到 `device/state`：

| 实体 | 首选字段 | 回退字段 |
| --- | --- | --- |
| `pv1_power` / `pv2_power` | `quick/state` 的 `pv1_p` / `pv2_p` | `pvs[].p` |
| `grid_port_power` | `quick/state` 的 `grid_on_p` | `grid[0].p` |

> 协议文档把这两个字段写作 `pPv1` / `pPv2` 与 `pAc`，但固件实际发送的是 `pv1_p` / `pv2_p` / `grid_on_p`。早期版本按文档拼写取值，结果**一次也没有命中**：逐口功率只能落到 5 分钟的 `pvs[].p`，并网口则长期 `unknown`（设备视图那条分支显示破折号）。现在两种拼写都接受，实测字段优先。

这解决了「设备页的并网端口比 System 页落后最多 5 分钟」的问题，也是主从机部署的前提：从机拿不到电表数据，**没有** `system_*` 可用，设备页必须自己站得住。储能机没有 `pv<n>_p` / `grid_on_p` 这些字段，会直接落到原来的 `device/state` 路径，行为不变。

`grid_port_power` 以 `requires_absent=CAP_SYSTEM_STATE` 门控：储能机用 `grid_on_power` 描述同一个端口，若不加区分会出现两个重复实体。

### 设备角色：`event/state` 的 `role` 决定标题标记与 `device` 视图

协议 §32「状态事件」是唯一说明**本机在系统中处于什么位置**的地方，主题为 `homeassistant/sensor/{dev_id}/event/state`，qos 1、retained。

实测报文（`RMI-4161A0209FF6`，2026-02，retain，qos 1）：

```json
{
  "role": "single",
  "has_meter": true,
  "has_plug": false,
  "switch": "ON",
  "ems_mode": "mqtt_ctrl",
  "output_power": 1000
}
```

三点需要注意：

1. **不是心跳。** 设备「连接后立刻发布，状态变化时」再发布，协议要求「每次均为全量快照，禁止只上报变化字段」。所以它绝不能进 `SOURCE_STALE_SECONDS`——给事件型主题加时间窗，等于保证设备在「什么都没变」一段时间后被判离线。`alarm/state`、TOU 的 ack/status 同样因此被排除在外。
2. **`event_state` 不在 `supported_topics` 清单里。** 同一台 RMI-4161 的 `attributes` 只声明了 `quick_state`、`device_state`、`alarm_state`、`switch_ctrl`、`output_power`、`power_ctrl`、`ems_mode`、`reboot`、`reset_ble_pin_code`。因此 `system_role` 实体**不做能力门控**——按清单门控反而会在真正发布该主题的机型上把实体藏掉。
3. **字段集合随机型变化。** 只有 `role` / `switch` / `ems_mode` 等基础字段每台必发；`has_meter` / `has_plug` / `has_solar2` 在从机上恒为 `false`（协议标注「从机不支持」），储能专属字段（`soc_h` / `heat` / `grid_p` / `eps_relay` 等）不在本集成范围内。

`has_meter` 除了说明「本机有没有并网计量点」，还**直接决定 System 页的功率流怎么画**：为 `false` 时电网与负载合并成单个「电网&负载」节点（详见上文「`has_meter: false` 时电网与负载合并成一个节点」）。它的值是转发到前端的——`sensor.<dev>_system_role` 的属性里带着整份 `event/state` 快照，卡片读属性而不是再订阅一次主题。

`role` 的取值与画法：

| `role` | 含义 | `system/*` 数据 | `system` 视图画法 | `device` 视图画法 |
| --- | --- | --- | --- | --- |
| `single` | 单机 | 完整（本机读电表） | 六节点全画 | 按 `pv_count` 画本机 PV 口 + 并网端口 |
| `master` | 主机 | 完整（代整系统读电表） | 同上，标题右侧显示「主机」标记 | 同上 |
| `slave` | 从机 | **缺失**（无电表，`sys_*` 恒 `unknown`） | **不生成 System 视图**（协议 §32 明确 `system/state` 只对「主机和单机」有效），标题右侧显示「从机」标记 | 同上 |
| *(缺失)* | 主题未到 / 老固件 | 按读数判断 | 六节点全画 | 同上 |

- `servant` 也见过（协议文档写 `slave`），在 `const.py` 的 `ROLE_ALIASES` 里统一映射成 `slave`，消费方无需关心拼写。
- 主题未到时 `role` 为 `None`，**不能**按 `single` 处理：否则从机在 HA 刚启动的瞬间会被画上电表支路，再跳变成纯本机图；同理 `None` 时也**不隐任何界面**。
- 从机那一路的兜底：`pv` 先读 `system_pv_power`，读不到退到本机 `pv1_power`；`grid` 先读 `system_grid_power`，读不到用 `grid_on_power` 取反（两者符号相反）。这就是「从机拿不到电表数据时设备页仍能显示」的完整链路。
- 头部标记只在 `master` / `slave` 出现。单机是绝大多数情况，显示一个恒定的「单机」只是噪音。

**rev.17：不支持的角色连界面都不出现（2026-11 改）**

最初从机的 System 页是「照画，只是读数显示 `—`」，实际用下来是错的：那一页永远一整页 `—`，用户只能靠标题旁边的标记去猜「少掉的节点是因为它是从机，不是因为卡片坏了」。协议 §32 已经把主从写得很清楚，所以现在按能力**删界面**而不是删读数：

- 从机（`slave`）**没有 System 标签页**：`lovelace.py` 的 `_async_sync_role()` 把 `path == "system"` 的整个 view 从 `views` 里摘掉，原样存在 `_ROLE_SYSTEM_KEY`（`g2_role_system_view`）旁边待命；
- 控制卡片里 **EMS 控制 / 输出功率 / 功率控制 / 分相（三相）** 这几组也从从机隐去：`hoymiles-g2-control.js` 的 `_role()` 归一化 `servant` → `slave` 后按组过滤，组内全部隐去时**连组标题一起不画**（`_group()` 返回空串，不会留下孤零零的标题）；
- 恢复是**逐字节**的：设备重新配对成主机/单机时，`_async_sync_role()` 把当初摘掉的那份 dict 原封不动放回去，用户的编辑一并在内。这也是这套逻辑**分两遍走**（先整页生成、再隐藏）的原因——生成时就过滤掉的话，就没有东西可以还原了。
- `role` 到得比仪表盘晚（`event/state` 是设备上线后才发的），所以角色同步**不靠** `_LAYOUT_VERSION` 升级触发，而是 `__init__.py` 里注册的 coordinator 监听器在角色变化时调用公开的 `lovelace.async_sync_role()`；另外每次注入或升级布局之后也会跟一次，因为重建会整体替换 `views`，把之前摘掉的表又带回来。

#### 两个视图里「光伏1 / 光伏2」**不是同一个东西**（2026-11 改）

这是最容易读错的一处，两边措辞也因此在图上加了括号限定：

| 位置 | 光伏1 | 光伏2 |
| --- | --- | --- |
| `system` 视图 | **系统内设备**的发电量（固件的 `sys_pv_p` 聚合） | **系统外**的发电量（第三个、邻家屋顶、任何电表能看到但不属于本系统的电源） |
| `device` 视图 | 本机第 1 个直流输入口（`pv1_power`） | 本机第 2 个直流输入口（`pv2_power`），只是**一个接口**，不是电源 |

- `system` 的 光伏2 只在电表看到大量馈电、而系统内设备又不发电时才会亮，它是量出来的差额来源，不是本机的接口。
- 因此 `_data()` 里 `pv2` **只读 `system_pv2_power`**，不再回退到 `pv2_power`。曾经有过这个回退，后果是二路机型的 `system` 页把**本机第二个组串**当成「系统外发电」画出来——两个完全不同的概念被接成了同一个数。没有该聚合值时显示 `—`，这是诚实的结果。
- `pv`（光伏1）**保留**了 `?? pv1_power` 回退：它仍然是「系统内发电」这个量的一个（偏小的）样本，只是量的范围小了，没有变成另一个概念。
- 图上的标题因此写成「光伏1（系统内）」/「光伏2（系统外）」，`device` 视图仍写「PV1」/「PV2」——物理接口就用固件的原始拼法。

#### 历史曲线的起坡不再从窗口角落开始（2026-11 改）

功率/电压/发电量三条历史曲线在**左端**会补一个「零锚点」，好让线从纵轴 0 上抬起来而不是凭空出现在某个高度。这个锚点最初直接取绘图区的左右边界（`x0` / `x1`），结果是在**当天第一条采样**距离窗口左边缘很远时（例如上午 10 点才开始发电），曲线会从 `00:00` 的角落一路缓坡爬上来，看起来像「一整天都在缓慢爬升」。

现在的锚点放在**第一个采样点前 `lead` 像素**处，`lead = clamp(10, 36, slot × 1.5)`（`slot` 是相邻采样点在横轴上的间距，也就是一个桶的宽度）：

- 斜坡因此**很陡**，读起来是「开始发电了」，而不是「隐约在爬」。
- 纵坐标仍然是 0，锚点还挂在基线 `baseAt(0)` 上，所以没有违反「必须从 0 起坡」这条。
- 只有确实有空间时才补锚点（`firstX > x0 + 0.5`），贴着左边界的不动。

**只有左端补锚点，右端不补**：窗口的右边界是「此刻」，随着时间推移会不断把新数据纳进来，最后一条采样就是最新的读数。右端如果把线拉回 0，等于声明「这条序列已经停了」，而且每过几分钟这条尾巴就要重画一次、形状不断变化——数据在长，画面却在一个假的地平线上抖动。所以右侧不做任何归零处理，曲线就停在最后一个真实读数上。

#### `device` 视图不再有「功率曲线」卡片（2026-11 改）

本机页原来还有一张把 PV / 电网 / 负载三条曲线画在一起的「功率曲线」卡。它被删掉了：这三条曲线本来就是 `system` 视图的内容（那一页画的是整栋房子），放在单机页既回答了没人问的问题，又和上面的「各光伏端口功率」重复，还让同样的三条序列每台设备存了两份。现在单机页是：功率流 + 告警 → 各光伏端口功率 → 电网电压 + 今日发电量。版面版本随之升到 **9**，`_migrate_device_drop_total_power()` 会把已存在的仪表板里那张卡删掉（按**序列**识别而不是按标题，所以改过名字的卡不会被误删；且只删「独占一个 grid 段」的那种，用户自己拖到别的卡旁边的不动，幂等）。

#### `system` 视图不区分主从（2026-11 改）

一开始是**按角色删支路**的：从机没电表，就不画负载和智能插座。用过之后发现这样读不出东西——同一个房子在主机页和从机页长得不一样，用户只能靠标题旁边的标记去猜「少掉的节点是因为它是从机，不是因为卡片坏了」。协议 §32 已经把主从写得很清楚，所以现在按能力**删界面**而不是删读数：

- 从机（`slave`）**没有 System 标签页**：`lovelace.py` 的 `_async_sync_role()` 把 `path == "system"` 的整个 view 从 `views` 里摘掉，原样存在 `_ROLE_SYSTEM_KEY`（`g2_role_system_view`）旁边待命；
- 控制卡片里 **EMS 控制 / 输出功率 / 功率控制 / 分相（三相）** 这几组也从从机隐去：`hoymiles-g2-control.js` 的 `_role()` 归一化 `servant` → `slave` 后按组过滤，组内全部隐去时**连组标题一起不画**（`_group()` 返回空串，不会留下孤零零的标题）；
- 恢复是**逐字节**的：设备重新配对成主机/单机时，`_async_sync_role()` 把当初摘掉的那份 dict 原封不动放回去，用户的编辑一并在内。这也是这套逻辑**分两遍走**（先整页生成、再隐藏）的原因——生成时就过滤掉的话，就没有东西可以还原了。
- `role` 到得比仪表盘晚（`event/state` 是设备上线后才发的），所以角色同步**不靠** `_LAYOUT_VERSION` 升级触发，而是 `__init__.py` 里注册的 coordinator 监听器在角色变化时调用公开的 `lovelace.async_sync_role()`；另外每次注入或升级布局之后也会跟一次，因为重建会整体替换 `views`，把之前摘掉的表又带回来。

#### 两个视图里「光伏1 / 光伏2」**不是同一个东西**（2026-11 改）

这是最容易读错的一处，两边措辞也因此在图上加了括号限定：

| 位置 | 光伏1 | 光伏2 |
| --- | --- | --- |
| `system` 视图 | **系统内设备**的发电量（固件的 `sys_pv_p` 聚合） | **系统外**的发电量（第三个、邻家屋顶、任何电表能看到但不属于本系统的电源） |
| `device` 视图 | 本机第 1 个直流输入口（`pv1_power`） | 本机第 2 个直流输入口（`pv2_power`），只是**一个接口**，不是电源 |

- `system` 的 光伏2 只在电表看到大量馈电、而系统内设备又不发电时才会亮，它是量出来的差额来源，不是本机的接口。
- 因此 `_data()` 里 `pv2` **只读 `system_pv2_power`**，不再回退到 `pv2_power`。曾经有过这个回退，后果是二路机型的 `system` 页把**本机第二个组串**当成「系统外发电」画出来——两个完全不同的概念被接成了同一个数。没有该聚合值时显示 `—`，这是诚实的结果。
- `pv`（光伏1）**保留**了 `?? pv1_power` 回退：它仍然是「系统内发电」这个量的一个（偏小的）样本，只是量的范围小了，没有变成另一个概念。
- 图上的标题因此写成「光伏1（系统内）」/「光伏2（系统外）」，`device` 视图仍写「PV1」/「PV2」——物理接口就用固件的原始拼法。

#### 历史曲线的起坡不再从窗口角落开始（2026-11 改）

功率/电压/发电量三条历史曲线在**左端**会补一个「零锚点」，好让线从纵轴 0 上抬起来而不是凭空出现在某个高度。这个锚点最初直接取绘图区的左右边界（`x0` / `x1`），结果是在**当天第一条采样**距离窗口左边缘很远时（例如上午 10 点才开始发电），曲线会从 `00:00` 的角落一路缓坡爬上来，看起来像「一整天都在缓慢爬升」。

现在的锚点放在**第一个采样点前 `lead` 像素**处，`lead = clamp(10, 36, slot × 1.5)`（`slot` 是相邻采样点在横轴上的间距，也就是一个桶的宽度）：

- 斜坡因此**很陡**，读起来是「开始发电了」，而不是「隐约在爬」。
- 纵坐标仍然是 0，锚点还挂在基线 `baseAt(0)` 上，所以没有违反「必须从 0 起坡」这条。
- 只有确实有空间时才补锚点（`firstX > x0 + 0.5`），贴着左边界的不动。

**只有左端补锚点，右端不补**：窗口的右边界是「此刻」，随着时间推移会不断把新数据纳进来，最后一条采样就是最新的读数。右端如果把线拉回 0，等于声明「这条序列已经停了」，而且每过几分钟这条尾巴就要重画一次、形状不断变化——数据在长，画面却在一个假的地平线上抖动。所以右侧不做任何归零
| `null` | 什么都不画 |

- `null` 的含义是**不知道**，不是「没告警」：没有告警实体（储能机、或没声明 `alarm_state` 的机型）与 `alarm/state` 还没收到，两者都归到这里。给一台根本没有告警传感器的机器画一个绿勾，等于凭空保证了一件没人检查过的事。
- 图标形状跟着**厂商 G3 App 的仪表盘**走：有告警是**实心红色三角 + 感叹号**，无告警是绿色对勾。两者都是 19 px，在这个尺寸上描边式的三角会糊成一团，所以三角用实心 `fill="currentColor"`，感叹号用白色镂空。
- **只画图标，不写条数，也不垫底板**（rev.19 改）：告警条数放在 `title` 悬浮提示里（「N 个活动告警」），图标本身 `background: none`，和卡片融为一体。原因是这个灯在原理图的左上角，叠了白底就变成一张贴纸；而数字挤在图标旁边会把 19 px 的图形压成两个小记号。条数并没有丢，只是移到了需要时才出现的地方——卡片右侧的告警列本身就会列出每一条。

#### 微逆原理图的底色跟随主题（rev.19 改）

`device` 视图的原理图原来在 `_inverterSvg()` 里硬编码了一块 `<rect fill="#ffffff">` 当背景板。浅色主题下看不出问题，深色主题下它就成了一块刺眼的白纸，而且和状态灯的白底叠在一起像是两张贴纸。现在这块矩形改挂 `class="pf-bg"`，`fill` 取 `var(--card-background-color, #ffffff)`，并由 `config.gradient === false` 控制是否绘制——**底色永远等于卡片底色**，视觉上消失。

连带的必要改动是**节点文字的颜色也要跟着主题走**：没有白底之后，写死的 `#1f2933`（数值）和 `#8b95a5`（说明）在深色背景上几乎读不出来。微逆原理图的这两行文字因此改挂 `.pf-iv` / `.pf-iv-c`，分别取 `var(--primary-text-color, #1f2933)` 与 `var(--secondary-text-color, #8b95a5)`。

**储能原理图不动**：它仍然画自己的白底、用固定的灰色文字。`system` 视图里的储能卡片是「一块独立的深色画面」，白底是有意为之的构图，不属于这次「融入卡片」的改动范围。图上的 `#ffffff` 与 `#1f2933` 因此分成两套，改主题变量前先确认改的是哪一套。

### 功率控制与输出功率的真实关系

`power_ctrl` 的 discovery 声明为 `min 0 / max 100 / step 1`，而同一台设备的 `output_power` 是 `100–800`，看起来自相矛盾，但实测证明这是**固件有意为之**，不是缺陷。

固件会在每次收到 `output_power/set` 之后，先向 `homeassistant/number/<dev_id>/power_ctrl/config` 发一条**空 payload**（等于删除该实体），再重新发布一份 `max` 等于刚刚接受的 `output_power` 的新配置。实测记录：

| 事件 | 声明的 `power_ctrl` `max` |
|---|---|
| 会话开始 | 132 |
| `output_power = 400` | 400 |
| `output_power = 800` | 800 |
| 空闲漂移 | 234 |
| `output_power = 150` | 150 |
| 恢复 `output_power = 132` | 132 |

所以语义是：**`output_power` 是硬件上限，`power_ctrl` 是在上限之内的目标值**。用户看到「只能调 0–132 W」，正是因为当时 `output_power = 132`。

关键在于这个上限是**软的**，声明的 `max` 只是一条 UI 建议：在声明 `max` 为 234 时下发 `power_ctrl = 700`，设备**照样接受并照做**（实测输出 715 W）。

由此带来两个必须由卡片处理的问题，否则界面看起来像坏了：

1. **滑条范围不能取 `power_ctrl` 声明的 `max`。** 否则设备被限制在 132 W 时，用户连「发 300 W」都做不到，而固件其实是接受的。**但也不能取 `output_power` 声明的 `max`**（早期版本这么做过，是错的）：主机（`role = master`）在 `output_power` 与 `power_ctrl` 两个主题上报的都是**整个系统**的合计能力，不是单机能力。实测 `RMI-4161A0209FF6`（额定 1000 W）在两个主题上都报 `max = 3000`，而同一序列号在旧的 `MI-` 前缀下报的是 `0 ~ 1000`；从机（`role = slave`）干脆不发任何 `number` 发现对象。滑条上界因此取**型号额定单机功率**（卡片内置表：`1650 → 800`、`4161 → 1000`、`4162 → 2000`），只有型号未知时才回退到声明的 `max`；下界仍取 `power_ctrl` 声明的 `min`（微逆 0，储能机为负）。

   反例就是本次修复的现场：9FF6 与 BFB5 同处一个系统，两台合计能发 3000 W，于是主机 9FF6 的滑条曾给出 `0 ~ 3000`（单机只能发 1000 W），从机 BFB5 的滑条因读不到声明范围而退化成 `-1000 ~ 0`。修复后两者分别为 `0 ~ 1000` 与 `0 ~ 2000`，且各自按正常正值下发。

   注意「输出功率」那一行**仍然**按 `output_power` 声明的范围渲染（9FF6 上是 `100 ~ 3000`）：主机上的它确实作用于整个系统，收窄会拿掉唯一能设置系统总功率的入口。只有 `power_ctrl` 是单机租约，不能继承这个合计值。

   `power_ctrl` 声明的 `max` 也不能当作能力上限——它是**瞬时**限制（FC22 当前声明 132，实际能做 800 W）。
2. **有效上限必须读 discovery 声明的属性，不能读 `output_power` 实体的 state。** 该实体只有 `command_topic`、没有 `state_topic`，state 只是 HA 最后一次下发的值，会立刻过期。

集成本身不去改写固件声明的范围（`discovery_override.py` 里 `number/{dev}/power_ctrl` 与 `output_power` 都走 `_patch_plain`，原样透传），所以这些数字一定来自设备。步进同样跟随声明：微逆 1 W，储能机 0.1 W。

### 两个 `number` 实体如何区分（别按 `_2` 后缀猜）

`power_ctrl` 与 `output_power` 是两个平级的 `number` 实体，HA 会给重名的实体加 `_2` 后缀，但**哪个是基础实体随固件而变**，实测三种机型三种顺序：

| 机型 | `number.<dev>` | `number.<dev>_2` |
| --- | --- | --- |
| RMI-4161A0209FF6（一拖二） | min 100 / max 1000 / step 1 → `output_power` | min 0 / max 1000 / step 0.1 → `power_ctrl` |
| RMI-1650A028FC22（一拖一） | min 0 / max 132 / step 1 → `power_ctrl` | min 100 / max 800 / step 1 → `output_power` |
| MSA 储能机 | min −2500 / step 0.1 → `power_ctrl` | min 100 / step 1 → `output_power` |

所以**后缀顺序不可作为判据**（三台里有两台与「顺序表」相反）。可靠的是声明的 `min`：`power_ctrl` 的下限恒在 0 或以下（储能机还能负到充电/馈电），`output_power` 的下限是硬件最小输出，实测恒为 100 W。

卡片因此先按 `min` 判定，仅在候选不唯一时退回后缀顺序，`entities:` 显式指定通常最高优先。若以后引入新机型，先在 HA 里核对这两个实体的 `min`/`step`，再决定是否需要钉住。

**但 `entities:` 钉住的值本身也要过一遍 `min` 校验。** 仪表盘由 `lovelace.py` 生成时会按当时的机型写死一份 `entities:`，而 `number.<dev>` 到底属于哪个键是随固件而变的（见上表）。早期版本给微逆的 Control 卡片写了 `entities: {output_power: number.<dev>}`，在 4161 上正确，但如果同一个仪表盘落到 1650（基础实体是 `power_ctrl`），两行就互换了范围——实测 1650 的「功率控制」显示 `100 ~ 800`、「输出功率」显示 `0 ~ 132`，即各自显示了对方的范围。现在的做法是两层防护：

* `lovelace.py` 不再写这条钉住项，并且 `_migrate_control_cards()` 会把已经写在磁盘上的仪表盘里的 `entities.output_power` 删掉（`g2_layout` 提升到 10 时执行一次）；
* 卡片侧新增 `_pinFits(key, entityId)`：钉住项声明的 `min` 与它所属的键矛盾时，这条钉住项被忽略并回落到上面的 `min` 判据。若实体没有声明 `min`（无从判断），仍以配置为准。

### 功率控制没有回执

`power_ctrl` 的 discovery 只给了 `command_topic`，**没有 `state_topic`**，因此 HA 会把它标成 `assumed_state: true`——界面显示的是 HA 自己最后一次下发的值，而不是设备的真实状态。

固件也确实**不发任何 ack**：在 `homeassistant/#`、`hoymiles_g2/#`、`+/<SN>/#`、`<SN>/#` 上监听 35 秒，下发后收到 0 条应答。实测指令确实生效（`power_ctrl=50` 后 `sys_plug_p` 稳定在 49.4–50.8 W 约 42 秒；`power_ctrl=700` 后输出 715 W），只是没有反馈通道。

**唯一真实的反馈是 `quick/state` 里的 `sys_plug_p`**（即 `sensor.system_plug_power`），滞后约 2–20 秒。判断一条功率指令是否生效，只能看这个数值是否朝目标靠拢。

### 功率控制是「租约」，约 60 秒后自动失效

这是「下发了数值，设备却不按它运行、功率来回抖」的真正原因：`power_ctrl` 不是一个**常驻设定**，而是一个**有超时的租约**。设备记住最后一次收到的目标值，大约 60 秒后丢弃它，回落到 `output_power`（当前为 132 W）。

两组对照实验（同一台 FC22，`output_power = 132`，目标 `power_ctrl = 77`）：

| 实验 | 做法 | 结果 |
| --- | --- | --- |
| 单次下发 | 只发一次 `77`，观察 150 秒 | 10:47:50–10:48:26 输出稳定在 **76.6–77.0 W**；到 10:48:50–10:48:58 已回到 **132.0 / 132.3 / 131.8 / 132.7**，之后一直在 132 附近。**超时 ≈ 60 秒** |
| 周期下发 | 每 20 秒重发 `77`，持续 180 秒 | 全程每一个 PV 峰值都落在 **74.1–78.4 W**，三分钟内**一次都没有**回到 132 |

结论：**要维持某个功率，必须至少每分钟重发一次。** 卡片里的「定时下发」行就是为此提供的开关（见 `docs/CARDS.zh-Hans.md`）。

除了这个超时，还有一层**物理抖动无法消除**：设备在不停地重扫 MPPT，`system_pv_power` 大约每 20 秒循环一次（约 1.4 W → 700 W → 140 W → 5 W → 1.4 W，实测峰值 698.4 / 499.8 / 407.0 / 340.6 W），`sys_plug_p` 会跟着它起伏（0 → 260 → 140 → 0）。即使定时器正常工作，瞬时读数也仍会随扫描周期摆动；判断是否受控应看**每个峰值对应的平台值**，而不是随手取一个瞬间采样。

### `ems_mode/state` 是集成的回声，不是设备真值

这是「串口日志里看不到 MQTT 控制下发」这一类问题的根源，必须牢记：

- `hoymiles_g2/<dev_id>/ems_mode/state` 由集成自己维护。`_handle_ems_mode_command` 会把**任何**被下发的模式原样回写到该主题（retained, qos 1），**不等待设备确认**。所以 HA 的 `select.ems_mode` 显示 `mqtt_ctrl`，只代表「用户/卡片下发过 `mqtt_ctrl`」。
- 设备的真值只有一处：`homeassistant/sensor/<dev_id>/device/state` 里的 `ems_mode` 字段（微逆约每 5 分钟一帧）。
- 实测（FF6, `RMI-4161A0209FF6`, 固件 `01.05.00`）：卡片下发 `ems_mode = mqtt_ctrl` 后，两个独立长窗口探针分别在同一时刻读到设备自报 `ems_mode=general`（16:49:58 与 16:59:59），而集成主题一直显示 `mqtt_ctrl`。
- **后果**：设备处于 `general` 时会**忽略** `power_ctrl`。此时卡片因为读到 `mqtt_ctrl` 而照常下发 `power_ctrl/set`，设备完全无反应、串口无任何打印——看起来像「下发失败」，其实是模式不对。keep-alive 的错误信息 `EMS mode is general, not mqtt_ctrl` 是同一现象的告警。
- `_async_sync_ems_mode_state` 会跟随设备的 `device/state`，但被 `EMS_MODE_ECHO_GUARD_SECONDS`（30 秒）压制，以免命令刚发出就被设备旧值弹回。因此短期内 UI 不可信。

排查顺序应该是：先看 `sensor.<dev>_ems_mode_device`（来自 `device/state`）是否等于 `mqtt_ctrl`，再怀疑下行链路。

#### 固件加了 `value_template` 之后，回声链路会静默断掉

上面这套回声依赖 `discovery_override._patch_ems_mode` 把 `select` 的 `state_topic` 改写到集成自己的主题。该补丁有一条明确的让路规则：

```python
if payload.get("value_template"):
    # 模板意味着固件自己会从它确实发送的载荷里取值，不要动。
    return False
```

固件 `01.05.00` 起，`ems_mode` 的 discovery 载荷带上了 `value_template: "{{ value_json.ems_mode }}"`，于是补丁不再改写，`state_topic` 退回固件自带的 `homeassistant/sensor/<SN>/event/state`。而 `event/state` 是**事件**主题——实测在 9FF6 上自 14:07:58 起长达数小时没有重新发布过。结果：

- 命令确实发出（`rc=0`，卡片也弹了 toast），但 `select` 读到的是几小时前的 `general`；
- 集成自己的回声主题仍在更新，只是已经没有实体在听了。

排查时如果看到 `select` 的 `state_topic` 是 `.../event/state`，就知道回声已经失效，此时**只能**以 `sensor.<dev>_ems_mode_device` 为真值。（是否要把补丁放宽成「模板指向事件主题也照样改写」，仍待决定：那会覆盖固件意图，且影响所有机型。）

#### 卡片如何避免这个问题：选点优先，但不压死设备真值

`hoymiles-g2-control` 的 `_emsMode()` 不再无条件采信 `select` 的实体状态，而是记住「本卡片最后一次下发 `ems_mode` 的时刻」（`_emsCommandAt`，同时持久化到 localStorage）：

- 实体状态与本地选点**一致** → 用选点；
- 实体状态**变了，且变更时间晚于**本卡片的最后一次命令 → 用实体状态（设备真的改了，界面要跟着走）；
- 其余情况（实体仍是旧值、或 `unknown`/`unavailable`）→ **用本地选点**。

这样即使设备完全不响应，用户点「MQTT 功率控制」后该行也保持高亮，功率控制滑杆与定时下发同时解锁，不会被下一次 `hass` 推送弹回。同时把设备实际报告的模式显示在行副标题里（`mqtt_ctrl · 设备 general`），把分歧摆到明面上，而不是假装一切正常。

### `output_power/set` 是否被设备收到，可用 `power_ctrl/config` 反证

`power_ctrl` 无 `state_topic`、无 ack，`output_power` 同样无回执，因此无法直接确认投递。但固件收到 `output_power/set` 后会重写 `power_ctrl` 声明的 `max`（见上文），于是：

> 下发 `output_power` 前后对比 `homeassistant/number/<dev_id>/power_ctrl/config` 里的 `max`。

实测：`max = 350`（等于此前下发过的 `output_power`）→ 下发 `output_power = 777` → retained config 先被清空（DELETED）→ 重新发布 `max = 777`。这证明消息**确实到达并被执行**。用同样的手法可验证任意下行主题的投递。注意此操作会改写设备的 `power_ctrl` 上界，验证完应恢复原值。

## 设备识别靠 PID，不靠前缀

设备的 `dev_id` 形如 `<客户端前缀>-<SN>`，例如 `RMI-4161A0209FF6`。其中：

- **前缀**（`RMI-`、`MSA-`）是 **MQTT 客户端前缀**，属于**用户设置项**，用户可以改成任意值（例如改成 `GARAGE-`，设备就变成 `GARAGE-4161A0209FF6`）。
- **SN 开头四位**是 **PID**（Product ID，产品识别码），由出厂决定，**不可更改**。

因此集成**一律不按前缀识别设备**，只按 PID 识别。前缀只作为 `dev_id` 的一部分原样保留 —— 因为它出现在设备的每一个 MQTT 主题里，集成必须用它才能和目标设备通信。

### PID 与产品对应关系

| PID | 产品 | PV 输入数 | 类别 |
| --- | --- | --- | --- |
| `1650` | HiFlow | 1 | 微逆 |
| `4160` | HiFlow Pro 1-in-1 | 1 | 微逆 |
| `4161` | HiFlow Pro 2-in-1 | 2 | 微逆 |
| `4162` | HiFlow Pro 4-in-1 | 4 | 微逆 |
| `2800` | HiBattery / Micro Storage | 按 `pv_num` 上报 | 储能 |

### 相关函数（`const.py`）

| 函数 | 作用 | 示例 |
| --- | --- | --- |
| `serial_body(dev_id)` | 去掉前缀，只留 SN | `RMI-4161A0209FF6` → `4161A0209FF6` |
| `serial_pid(dev_id)` | 取 SN 前四位，非四位数字返回 `None` | `RMI-4161A0209FF6` → `4161` |
| `is_inverter_dev_id(dev_id)` | PID 是否属于微逆集合 | `GARAGE-4161A0209FF6` → `True` |
| `pv_count_from_dev_id(dev_id)` | 由 PID 得到 PV 输入数 | `RMI-4162AAAA` → `4` |
| `model_from_dev_id(dev_id)` | 由 PID 推断产品族（兜底用） | `MSA-2800...` → `HiBattery` |

`serial_body()` 取的是 `split("-")[-1]`（最后一段）而不是 `split("-", 1)[1]`，这样即使前缀本身含 `-`（如 `my-prefix-4161…`）也不会把 PID 取错。

### 三处需要同步维护的表

PID 与属性的映射分散在前后端，改动时必须**同时**更新：

| 位置 | 表名 | 用途 |
| --- | --- | --- |
| `const.py` | `PID_PV_COUNT` | Python 侧端口数与型号推导（唯一真值源） |
| `www/hoymiles-g2-power-flow.js` | `IV_PV_COUNT_BY_CODE` | 功率流卡片画几路 PV |
| `www/hoymiles-g2-battery.js` | `IV_PID_PV_COUNT` | 电池卡片的微逆判定兜底 |

JS 侧的两张表只是**兜底**：正常情况下卡片从实体里就能拿到端口数，只有实体尚未建立时才回退到按 PID 查表。

### 发现流程（`mqtt_util.async_discover_dev_ids`）

1. 订阅 `homeassistant/switch/+/config`（固件在连接时用 retained 消息发布的发现主题）。
2. 从主题里取出 `parts[2]` 作为 `dev_id`。
3. 用 `serial_pid()` 取出 PID，**不在 `KNOWN_PIDS` 里的直接丢弃**。
4. 返回**带前缀的完整** `dev_id`。

第 3 步是必需的：这个通配符也会匹配到其它集成（例如官方 `hoymiles` 集成管理的 `MSA-2804*` / `MSA-2805*` 储能机、以及 `homeassistant/*` 下的杂项）发布的主题，不过滤会全部涌进选择器里。实测过滤前后的差异：

```
接受： MI-4161A0209FF6, MSA-280024180016, MSA-280024210095,
       RMI-1650A028FC22, RMI-4161A0209FF6, RMI-4161A020A04A
丢弃： 19 台 MSA-2804* / MSA-2805*（属于官方 hoymiles 集成）
```

注意 `MI-4161A0209FF6` —— 前缀已被用户改过，仍然被正确识别，正是本次改动的目标。

### 配置流程的校验

`config_flow.py` 允许**自由输入** `dev_id`（`custom_value=True`），但要求 SN 前四位是可读的 PID，否则报 `dev_id_invalid`：

- 这个校验**只管 SN，不管前缀** —— 前缀可以随便改。
- 保留自由输入是为了让 PID 比本版本更新的机型也能安装；完全无法解析出四位数字的输入才会被拒绝（那说明是笔误，装上也永远收不到数据）。

## 能力门控

集成不再靠型号名判断设备形态，而是读取固件在连接时发布的 retained `homeassistant/sensor/<dev_id>/attributes` 里的 `supported_topics`：

- 含 `system_state` → 储能机（MSA）：创建电池、电池包、PV3/PV4、并网口、逆变侧、分时计划等全部实体。
- 不含 `system_state` → 微逆（RMI）：只创建双方都有的实体（`system_pv_power`、`system_grid_power`、`system_load_power`、`rssi`、`grid_on_*`、`pv*_power`、`ems_mode_running` 等），外加由 `pvs[].ed` / `et` 支撑的逐口电量实体。
- 门控是双向的：`requires` 表示“必须有该能力”，`requires_absent` 表示“必须没有该能力”。后者专门用于只在缺少某主题的机型上才存在的数据，例如微逆的 `pvs[]` 电量。
- `phase_output_power` 不在 `supported_topics` 里，它只能通过 discovery 对象是否存在来判断，由 `discovery_override.py` 的 `on_object` 回调汇报给协调器。

`attributes` 尚未到达时能力集合按"全部支持"处理，等待上限 3 秒，因此升级集成不会误删本来存在的实体。

`event_state`（§32 `event/state`）**故意不参与能力门控**：它不在 `supported_topics` 里，但设备实际在发布该主题。按清单门控只会在真正支持它的机型上把 `system_role` 实体藏掉，所以那个实体无条件创建（见图纸「设备角色」一节）。

微逆实测的 `supported_topics`（`RMI-4161A0209FF6`）：

```
alarm_state, device_state, ems_mode, factory_reset, output_power,
power_ctrl, quick_state, reboot, reset_ble_pin_code, switch_ctrl
```

注意**没有** `system_state` 和 `tou_get` —— 这正是微逆不会长出电池 / 电池包 / 逆变侧 / 分时计划实体的原因。早期版本在每台设备上都创建 `tou_*` 实体，导致微逆的 Control 卡片上有个永远超时的「获取 TOU 计划」按钮；现在 `_async_prune_stale_entities()` 会把这类过时实体从注册表移除。


## 自动生成的仪表盘

集成首次加载时为每台设备创建一个 storage 仪表盘，`url_path` 为 `g2-<slug(序列号)>`（如 `g2-rmi_4161a0209ff6`），标题默认就是裸序列号（用户重命名后不会被覆盖）。

### 三个视图

| 视图 | 内容 |
| --- | --- |
| System | 全宽功率流、今日发电 + 累计发电仪表、功率历史曲线（PV / 电网 / 负载）、发电量柱状图（日/月/年 + 三个统计笉片） |
| Device | 无告警时：功率流横跨整行（不设宽度上限，按卡片宽度等比放大）；有告警时：功率流（24 列）+ 告警卡（24 列）各占半行。其下是各光伏端口功率、电网电压 + 今日发电量 |
| Control | 功率控制卡、keep-alive 状态（从机上只剩部分分组，见 rev.17） |

Device 视图首行刻意让两张卡是**同一个 `_grid()` 内的兄弟卡**：嵌套 `grid` 卡会强制等分，而两个独立 section 在 `max_columns` 生效后会上下堆叠。24 + 24 = 48 正好等于一个 `column_span: 4` section 的实测列数（实测：section 宽 1354 px，48 列、列宽 20.375 px、列间隙 8 px）。

为何从 27 + 9（3:1）改成 1:1（rev.18）：告警卡本身是 `only_when_alarm`，设备安静时它根本不显示，用户实际看到的永远只有流图占左边 3/4、右边空着一条——正是厂商 App 不会做的事。现在告警卡在场时两张卡等宽并排（厂商 G3 那一页就是这么排的），告警卡不在时流图自动扩到整行（卡片里的 `_syncRowSpan()` 按告警数量决定 `grid-column: 1 / -1` 还是原值）。

为何 rev.18 的 18 + 18 仍留白（rev.19 修掉）：18 + 18 = 36，只占满 48 列中的 36 列，所以两张卡实测各 503 px、整行 1354 px，右侧空出 348 px。24 + 24 才是真正占满整行的等分。同时 `max_width` 从 640 改为 `0`（=不设上限）：`_wrapStyle()` 那时直接返回 `max-width:none`，SVG 按 `width:100%` 填满单元格再等比缩放；否则即使卡片被拉宽，图仍卡在 640 px 居中，看上去依旧没变。System 视图的流图不带 `variant`，迁移从不触碰，仍保留自己的 700 px。

> 0.6.x 修正了上一条的副作用：`max-width:none` 让图随单元格一起变宽，于是「告警卡在/不在」两种状态下**卡片高度不一样**。现在 `max_width: 0` 且卡片占满整行时，`_wrapStyle()` 给出的是 `max-width:min(100%, <实测半行宽度>px)`——图保持半行时的尺寸并居中，卡片只是变长。见上文「`max_width: 0` 表示不设上限」处的说明。

> `_syncRowSpan()` 写的元素也从 `hui-card` 改成了**真正带 `grid-column` 的那层祖先**（新增 `_gridItem()`）：当前 HA 的 sections 布局中 `hui-card` 是 `display: inline`，被包在一个 `div.card` 里，`grid-column` 在内层 div 上，写 `hui-card` 是无效操作。

### System 视图的三条曲线是**三条独立测量**，不是拆开的同一个总量

「光伏功率 / 电网 / 负载」这三条序列分别来自 `sensor.<dev>_system_pv_power`、`_system_grid_power`、`_system_load_power`，也就是 1 秒 `quick/state` 里的 `sys_pv_p` / `sys_grid_p` / `sys_load_p` —— **设备原样上报，卡片不参与任何运算**。它们分别单独测量、单独上报，所以：

- 三条曲线的**高度不会相加成一个数**，`_history()` 因此显式写了 `stack=False`（堆叠意味着「加起来是总量」，这三个不是）。
- 同一时刻 `光伏 − 电网 = 负载` **不一定精确成立**。差值来自三处：三个量各自的采样/上报时刻相差几十到几百毫秒（历史图按 recorder 的统计桶对齐，缺失点从前一个桶**前向填充**，见 `_build()`）；设备自身的自耗电与变换损耗不被 `sys_load_p` 计入；以及电表与逆变器各自的计量误差。
- 所以看到「113.0 W 光伏 / −31.8 W 电网 / 75.0 W 负载」而差几瓦是**正常现象**，不是卡片在编数字，也不是有数据丢了。卡片没有任何地方做功率平衡校正。

### 布局版本与迁移

存储里带一个 `g2_layout` 版本标记（键为 `_LAYOUT_KEY`，当前 `_LAYOUT_VERSION = 22`）。规则：

- **新设备**：直接以当前版本落盘，**不跑迁移**。
- **已存在的设备**：每次集成加载时按版本链逐项修补（`_migrate_axis_cards` → `_migrate_control_cards` → `_migrate_energy_total_card` → `_migrate_device_alarm_card` → `_migrate_device_alarm_columns` → `_migrate_device_drop_total_power` → `_migrate_system_energy_chart` → …），修完写回当前版本。
- 迁移**只改集成自己生成过的值**：用户选的 `max_width`、手挑的告警实体、重命名的视图、手动添加的卡片都保留。`_migrate_device_alarm_columns()` 仅把集成历史上写过的 `380 / 640 / 700 / 1100` 这几种 `max_width` 改成当前值 `0`，别的数字（用户自己填的）一律不动。
- 每个仪表盘每进程只检查一次（`_LAYOUT_CHECKED`），因为 `LovelaceStorage` 会缓存配置在内存里。

### 新设备为何能自动得到同一套配置

布局里的每一项都由序列号推导，没有按具体设备硬编码：

| 参数 | 推导方式 |
| --- | --- |
| 是否微逆 | `_is_inverter()` → `is_inverter_dev_id()` → SN 前四位的 PID 属于 `INVERTER_PIDS` |
| PV 端口数 | `coordinator.pv_count`：固件 `pv_num` → `PID_PV_COUNT` 查表 → `PV_COUNT_MAX`（4） |
| 型号名 | `_resolve_model()`：设备注册表 → `model_from_dev_id()` 按 PID 推导 |
| 告警实体 id | `_alarm_entity_id()`：按 `unique_id` 查注册表 → 回退序列号拼法 |

所以接入新设备**不需要**逐台部署或手工配置，集成加载完它就有相同的三视图与布局。

### 前端卡片如何解析实体（设备改名后仍然有效）

`hoymiles-g2-power-flow.js` / `-battery.js` / `-energy-sankey.js` / `-tou-editor.js` 都要在运行时把「后缀」换成真实 `entity_id`，按代价从低到高依次尝试：

1. `config.entities[<后缀>]` 手填覆盖（唯一能绕过全部推导的入口）；
2. 常规拼法 `<domain>.<slug(dev_id)>_<后缀>`；
3. 前缀扫描：`entityId` 以 `<domain>.<slug(dev_id)>` 开头，且**归一化后**的余下部分等于后缀。归一化（去掉所有非字母数字）是为了让 `pack1_soc` 与 slug 化之后的 `pack_1_soc` 等价；
4. **序列号扫描**：把整个 `entity_id` 归一化后查找序列号，要求序列号**之后**的部分恰好等于后缀。

第 4 步是设备**改名**后的唯一救命路径。HA 改名会重写该设备下所有实体的 `entity_id`，于是 `sensor.rmi_4161a0209ff6_grid_port_power` 变成 `sensor.wo_shi_rmi_4161a0209ff6_grid_port_power`，第 2、3 步依赖的 `<slug(dev_id)>_` 前缀就消失了。序列号本身永不变，所以按「序列号之后的尾巴」比对既能锁定本机，又不会让 `soc` 误命中 `system_soc`（只比较序列号之后的部分）。

`hass.entities` 这条 `unique_id` 回退**不能依赖**：前端注册表默认不带 `unique_id`（需要 `?extended`），实测返回 `undefined`，所以它只是象征性的最后一步。`lovelace.py` 里的 `_alarm_entity_id()` 是后端调用、能拿到完整注册表，因此那里按 `unique_id` 反查是可靠的。

现象：第 4 步缺失时，**Power Flow 卡的并网端口节点会一直显示 `—` 或陈旧的 5 分钟值**（`_read()` 拿到 `null` 后回退到 `grid_on_power_5_min`），而 PV 端口因为 id 恰好没被重写仍然正常 —— 这就是「只有并网端口不跟随秒级数据」的成因。

## 协议 §46「HA 上线通知」：`homeassistant/status`

固件订阅 `homeassistant/status`，用于得知 Home Assistant 的上线/下线。这是 HA 的 MQTT 集成**自带**的行为 —— HA 自己在连接 broker 时就会发布这条 retained=false 的消息，配置存在 `/config/.storage/core.config_entries` 里：

```json
"birth_message": {"payload":"online",  "qos":0, "retain":false, "topic":"homeassistant/status"}
"will_message":  {"payload":"offline", "qos":0, "retain":false, "topic":"homeassistant/status"}
```

也就是说这一项**不需要集成做任何事**：`hoymiles_g2` 里没有任何发布 `homeassistant/status` 的代码，HA 核心已经发了。

### 设备收到后做什么（实测）

关键问题：设备重连后是**只报当前数据**，还是会补报历史？实测结论是**只报当前快照**。

测试方法：先录 8 秒连接时的 retained 快照，再发布一次 `homeassistant/status=online`（qos 1），随后录 45 秒的重报内容，逐条比对。

```
连接时上报：  attributes, event/state, quick/state(1Hz), availability,
              ems_mode/state, power_ctrl/keepalive
上线后重报：  alarm/state, attributes, event/state, quick/state,
              power_ctrl/keepalive

内容完全相同： attributes, event/state
数值有差异：   quick/state, power_ctrl/keepalive   （仅实时抖动）
只在连接时：   availability, ems_mode/state
只在上线后：   alarm/state
```

差异只有实时抖动（`grid_on_p: 203.9` → `204.0`，keepalive 的 `count: 20` → `21`），没有任何时间戳，也没有任何历史序列。

因此：

- **不能**指望靠这次重报补回 HA 停机期间丢失的数据 —— 设备不会补历史。
- 所有 payload 里都**没有时间戳**，即使补报也无法还原到原始时刻。
- 重报的价值是「让 HA 重新建立实体状态」，而不是「补齐历史」。历史曲线只能靠 HA 自己持续记录。

### 一次真实 HA 重启的时间线

从 HA 真正重启的抓包看（单位：秒）：

```
 33.76  homeassistant/status = offline      ← HA 的 will 消息
 44.97  device/state                        ← 停机期间错过的数据
 50.50  event/state                         ← 停机期间错过的数据
 71.44  homeassistant/status = online       ← HA 自己的 birth
 71.45  event/state                         ← 0.01 s 后设备立刻反应
 72.29  attributes                          ← 设备据此重建发现
 75.50  event/state
 75.96  alarm/state
```

注意这里有一个**竞态**：HA 的上线通知在 MQTT 连接那一刻就发出了，而 `hoymiles_g2` 的配置条目此时可能还没建立订阅，于是设备的这次重报有概率被集成**错过**（虽然 HA 核心自己的 MQTT 订阅仍会收到）。因为重报内容与连接时完全相同、且没有时间戳，错过它不会造成数据错误，最多是实体状态等到下一次 `quick/state`（1 秒内）才刷新。

> 若要彻底消除这个竞态，可以在 `async_setup_entry` 里、订阅建立之后再补发一次 `homeassistant/status=online`（用 `hass.data` 去重）。本版本**未实现**，因为实测影响仅为不到 1 秒的刷新延迟。
