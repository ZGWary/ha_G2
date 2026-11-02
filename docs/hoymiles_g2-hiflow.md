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

`RMI-1650A028FC22`（固件 `01.03.00`）只发布 retained 的 `config` / `attributes` / `availability`，**不发布 `quick/state` 遥测**，因此实时功率与今日发电显示为 `—`。控制下发链路正常（已验证 `homeassistant/number/RMI-1650A028FC22/output_power/set => 400`）。
