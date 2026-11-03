# HiFlow (RMI) 微逆支持补丁 — `hoymiles_g2`

本目录下的 `hoymiles_g2-hiflow.patch` 记录了让 `hoymiles_g2` 集成自动识别 **RMI 前缀的 HiFlow 微型逆变器** 所需的全部改动。

> `hoymiles_g2` 是 Home Assistant 的内置集成，源码位于 HA 容器内 `/config/custom_components/hoymiles_g2/`，**不在本仓库中**。因此改动以补丁形式保存，升级集成后需要重新应用。

## 改动概览

| 文件 | 改动 |
| --- | --- |
| `const.py` | 新增 `HIFLOW_IMAGE_FILENAME`、`FRONTEND_IMAGES`、`HIFLOW_IMAGE_URL` |
| `__init__.py` | `_collect_assets()` 同时把 `FRONTEND_IMAGES` 注册为静态路由；`add_extra_js_url` 跳过非 `.js` 资源 |
| `www/hoymiles-g2-battery.js` | 微逆模式：设备识别、`_isMicroInverter()`、`_microInverterBody()`、样式 |
| `www/hiflow.png` | 产品图（27087 B），随卡片一起由集成提供 |

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

- `model` 含 `HiFlow`，或 `dev_id` 以 `RMI-` 开头 → 显示产品图 + 光伏输入 / 并网输出 / 今日发电。
- 其他（MSA / `HiBattery`）→ 保持原有电池堆栈示意图，行为不变。
- 可用 `variant: inverter` / `variant: battery` 强制指定，`image:` 覆盖产品图。

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

### 功率控制没有回执

`power_ctrl` 的 discovery 只给了 `command_topic`，**没有 `state_topic`**，因此 HA 会把它标成 `assumed_state: true`——界面显示的是 HA 自己最后一次下发的值，而不是设备的真实状态。

固件也确实**不发任何 ack**：在 `homeassistant/#`、`hoymiles_g2/#`、`+/<SN>/#`、`<SN>/#` 上监听 35 秒，下发后收到 0 条应答。实测指令确实生效（`power_ctrl=50` 后 `sys_plug_p` 稳定在 49.4–50.8 W 约 42 秒；`power_ctrl=700` 后输出 715 W），只是没有反馈通道。

**唯一真实的反馈是 `quick/state` 里的 `sys_plug_p`**（即 `sensor.system_plug_power`），滞后约 2–20 秒。判断一条功率指令是否生效，只能看这个数值是否朝目标靠拢。

## 能力门控

集成不再靠型号名判断设备形态，而是读取固件在连接时发布的 retained `homeassistant/sensor/<dev_id>/attributes` 里的 `supported_topics`：

- 含 `system_state` → 储能机（MSA）：创建电池、电池包、PV3/PV4、并网口、逆变侧、分时计划等全部实体。
- 不含 `system_state` → 微逆（RMI）：只创建双方都有的实体（`system_pv_power`、`system_grid_power`、`system_load_power`、`rssi`、`grid_on_*`、`pv*_power`、`ems_mode_running` 等），外加由 `pvs[].ed` / `et` 支撑的逐口电量实体。
- 门控是双向的：`requires` 表示“必须有该能力”，`requires_absent` 表示“必须没有该能力”。后者专门用于只在缺少某主题的机型上才存在的数据，例如微逆的 `pvs[]` 电量。
- `phase_output_power` 不在 `supported_topics` 里，它只能通过 discovery 对象是否存在来判断，由 `discovery_override.py` 的 `on_object` 回调汇报给协调器。

`attributes` 尚未到达时能力集合按"全部支持"处理，等待上限 3 秒，因此升级集成不会误删本来存在的实体。
