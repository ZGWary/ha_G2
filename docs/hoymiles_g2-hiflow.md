# HiFlow (RMI) 微逆支持补丁 — `hoymiles_g2`

本目录下的 `hoymiles_g2-hiflow.patch` 记录了让 `hoymiles_g2` 集成自动识别 **RMI 前缀的 HiFlow 微型逆变器** 所需的全部改动。

> `hoymiles_g2` 是 Home Assistant 的内置集成，源码位于 HA 容器内 `/config/custom_components/hoymiles_g2/`，**不在本仓库中**。因此改动以补丁形式保存，升级集成后需要重新应用。

## 改动概览

| 文件 | 改动 |
| --- | --- |
| `const.py` | 新增 `HIFLOW_IMAGE_FILENAME` / `HIFLOW_PRO_IMAGE_FILENAME`、`FRONTEND_IMAGES`、`HIFLOW_IMAGE_URL` / `HIFLOW_PRO_IMAGE_URL` |
| `__init__.py` | `_collect_assets()` 同时把 `FRONTEND_IMAGES` 注册为静态路由；`add_extra_js_url` 跳过非 `.js` 资源 |
| `www/hoymiles-g2-battery.js` | 微逆模式：设备识别、`_isMicroInverter()`、`_microInverterBody()`、样式 |
| `www/hoymiles-g2-power-flow.js` | 微逆布局 `variant: inverter`：只画光伏 + 并网端口，中间放产品图 |
| `www/hiflow.png` | 产品图（27087 B，736×486），随卡片一起由集成提供 |
| `www/hiflow-pro-2in1.png` | HiFlow Pro 2-in-1 产品图（38150 B，360×168 透明裁切），供电网卡片微逆布局使用 |

## 应用方式

在以 `hoymiles_g2` 为当前目录的父级执行：

```bash
cd /config/custom_components
patch -p1 < ha_G2/docs/hoymiles_g2-hiflow.patch
```

然后复制产品图并把预压缩副本删掉（旧 `.js.gz` 会被 aiohttp 优先返回，导致改动看不到）：

```bash
cp /config/www/hiflow.png /config/custom_components/hoymiles_g2/www/hiflow.png
rm -f /config/custom_components/hoymiles_g2/www/*.js.gz
ha core restart
```

## 卡片行为

### 电池卡片（`hoymiles-g2-battery`）

- `model` 含 `HiFlow`，或 `dev_id` 以 `RMI-` 开头 → 显示产品图 + 光伏输入 / 并网输出 / 今日发电。
- 其他（MSA / `HiBattery`）→ 保持原有电池堆栈示意图，行为不变。
- 可用 `variant: inverter` / `variant: battery` 强制指定，`image:` 覆盖产品图。

### 电网卡片（`hoymiles-g2-power-flow`）

这张卡片有两套画法，**由 `variant` 显式选择，不自动识别机型**：

- 默认（`variant` 留空）→ 四支路储能示意图。`system` 视图一直用这套，**不受影响**。
- `variant: inverter` → 微逆画法：产品图居中，**并网端口在右上**，**PV-1 在左下、PV-2 在右下**（与官方 App 一致）；没有电池 / 负载 / 智能插座 / 离网端口。

> 之所以不做自动识别：同一张卡片既用于储能机的 `system` 视图，也用于微逆的 `system` 视图（RMI 同样有 `sys_pv_p` / `sys_grid_p`），若靠 `RMI-` 前缀自动切换，`system` 视图也会一起被改掉。

```yaml
# 微逆的 device 视图
- type: custom:hoymiles-g2-power-flow
  dev_id: RMI-4161A0209FF6
  variant: inverter
  image: /hoymiles_g2_static/hiflow-pro-2in1.png   # 默认即此图，可省略
  title: 我的家
  show_title: false
  max_width: 700
```

微逆画法的并网端口：

- 数值取**绝对值**，正文固定为「并网端口」，不随符号改写（避免「绝对值 + 方向字幕」自相矛盾）。
- 方向由**流动珠子**和连线颜色表达：`> 0` 取电，珠子朝机组方向流动、线为 `#4a90d9`；`< 0` 馈电，珠子朝电网方向流动、线为 `#f59e0b`。
- `|P| < 5 W` 时不显示珠子，产品图降为 55% 透明度；`dim_when_idle: false` 可关掉这个变暗效果。
- 光伏节点与储能画法一致：`sys_pv_p` 为负（夜间耗电）时珠子反向。

#### 画布几何

画布固定 `700 × 430`，坐标写死在 `hoymiles-g2-power-flow.js` 的 `IV_*` 常量里：

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `IV_PHOTO_W` / `IV_PHOTO_MAX_H` | 300 / 190 | 产品图的最大宽高，实际宽度取 `min(300, 190 × 宽高比)` |
| `IV_PHOTO_CX` / `IV_PHOTO_CY` | 350 / 200 | 产品图中心 |
| `IV_NODE_PV1` | (95, 330) | PV-1 左下 |
| `IV_NODE_PV2` | (605, 330) | PV-2 右下 |
| `IV_NODE_GRID` | (605, 90) | 并网端口右上 |
| `IV_TERMINAL_INSET` | 22 | 连线终点距产品图边缘的内缩量 |
| `IV_CORNER` | 10 | 折线圆角半径 |

- 产品图按 `IV_PHOTO_ASPECT` 里登记的宽高比计算包围盒（`hiflow.png` = 736/486，`hiflow-pro-2in1.png` = 360/168）；未登记的图按 `360/168` 兜底。
- 三条连线都用 `elbowRoute()` 生成正交折线（`M / V|H / Q / H`），终点落在产品图左右边缘、纵向内缩 22 px 处；PV 段从下方节点向上接入，并网段从右上节点向下接入。
- 左侧标签在圆圈下方，并网端口标签在圆圈**上方**（`above: true`），避免压到产品图。
- 并网端口的数值正文用绝对值，方向只由珠子与线色表达（见下）。

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


## 已知限制

`RMI-1650A028FC22`（固件 `01.03.00`）**会**发布 `quick/state` 与 `device/state`，但内容比储能机（MSA）少得多：

| 主题 | 频率 | 微逆（HiFlow）内容 |
| --- | --- | --- |
| `quick/state` | 1 Hz | 仅 5 个字段：`sys_pv_p` / `sys_plug_p` / `sys_grid_p` / `sys_load_p` / `sys_sp_p` |
| `device/state` | 5 min | 单条 `grid[]`（`type=grid_on`，只有 `v/i/f/p/q`）、`rssi`、`pv_num`、`pvs[{id,p,ed,et}]`、`ems_mode` |
| `attributes` | retained | `supported_topics` 能力清单 |
| `system/state` | — | **从不发布** |
| `alarm/state` | — | 声明在 `supported_topics` 中，但实测从未出现 |
| `tou_*` | — | **从不发布**（无分时计划） |

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

1. **滑条范围不能取 `power_ctrl` 声明的 `max`。** 否则设备被限制在 132 W 时，用户连「发 300 W」都做不到，而固件其实是接受的。卡片改为按 `output_power` 声明的 `max`（额定上限，800 W，永不变化）作为滑条上界，把当前有效上限作为**提示文字**展示，而不是硬性阻断。
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

卡片因此先按 `min` 判定，仅在候选不唯一时退回后缀顺序，`entities:` 显式指定永远最高优先。若以后引入新机型，先在 HA 里核对这两个实体的 `min`/`step`，再决定是否需要钉住。

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

### `output_power/set` 是否被设备收到，可用 `power_ctrl/config` 反证

`power_ctrl` 无 `state_topic`、无 ack，`output_power` 同样无回执，因此无法直接确认投递。但固件收到 `output_power/set` 后会重写 `power_ctrl` 声明的 `max`（见上文），于是：

> 下发 `output_power` 前后对比 `homeassistant/number/<dev_id>/power_ctrl/config` 里的 `max`。

实测：`max = 350`（等于此前下发过的 `output_power`）→ 下发 `output_power = 777` → retained config 先被清空（DELETED）→ 重新发布 `max = 777`。这证明消息**确实到达并被执行**。用同样的手法可验证任意下行主题的投递。注意此操作会改写设备的 `power_ctrl` 上界，验证完应恢复原值。

## 能力门控

集成不再靠型号名判断设备形态，而是读取固件在连接时发布的 retained `homeassistant/sensor/<dev_id>/attributes` 里的 `supported_topics`：

- 含 `system_state` → 储能机（MSA）：创建电池、电池包、PV3/PV4、并网口、逆变侧、分时计划等全部实体。
- 不含 `system_state` → 微逆（RMI）：只创建双方都有的实体（`system_pv_power`、`system_grid_power`、`system_load_power`、`rssi`、`grid_on_*`、`pv*_power`、`ems_mode_running` 等），外加由 `pvs[].ed` / `et` 支撑的逐口电量实体。
- 门控是双向的：`requires` 表示“必须有该能力”，`requires_absent` 表示“必须没有该能力”。后者专门用于只在缺少某主题的机型上才存在的数据，例如微逆的 `pvs[]` 电量。
- `phase_output_power` 不在 `supported_topics` 里，它只能通过 discovery 对象是否存在来判断，由 `discovery_override.py` 的 `on_object` 回调汇报给协调器。

`attributes` 尚未到达时能力集合按"全部支持"处理，等待上限 3 秒，因此升级集成不会误删本来存在的实体。
