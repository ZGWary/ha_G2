<#
.SYNOPSIS
    构建可部署的 `hoymiles/inverter/` 子包（微逆部分）。

.DESCRIPTION
    仓库里 `_g2src/hoymiles_g2` 是**独立集成**形态（domain = hoymiles_g2，
    静态目录 /hoymiles_g2_static）。客户现场把微逆做成**子包**形态：
    挂在官方 `hoymiles` 集成下的 `hoymiles/inverter/`，共享 parent 的
    domain，静态目录为 /hoymiles_inverter_static。

    两种形态的差异分三类，脚本对它们分别处理：

      1. **前端资源**（www/*.js）—— 可机械转换。
         `from ..` 之类改写不涉及，只需 LF 换行 + 静态路径替换。
         已用现场部署副本逐字节验证：12/13 个 js 转换后与现场完全一致，
         仅 power-flow.js 因现场版本较旧而存在真实差异。

      2. **转换安全的后端**（9 个 .py）—— 可机械转换。
         只有 `from ..X` -> `from .X` 与静态路径替换，转换后与现场逐字节一致。

      3. **形态结构性差异**（5 个 .py）—— **不可机械转换**。
         `__init__.py` / `const.py` / `services.py` / `options_flow.py`
         在子包形态里是**裁剪版**：const 从 parent 重新导出符号、
         services 只注册 4 个微逆专用服务（其余 6 个留在 parent）、
         options_flow 只保留 region/charts/reboot。
         `region.py` 函数内 `from ..const` 与独立形态的 `from .const` 方向相反。
         这些必须来自 `_g2src/hoymiles_g2/_packaged/` 覆盖目录，
         否则脚本**拒绝生成**（避免把独立形态的代码塞进子包而破坏现场）。

    parent 包（`custom_components/hoymiles` 本身）不在本脚本职责内：
    仓库里是 0.5.1，现场是 0.7.0（多出 dashboard.py / power_repeat.py），
    直接重建会降级并丢文件。这里只产出 `inverter/`。

.PARAMETER OutDir
    输出根目录，默认 `dist/hoymiles`。最终子包位于 `<OutDir>/inverter/`。

.PARAMETER Clean
    构建前清空 `<OutDir>/inverter/`。

.PARAMETER VerifyAgainst
    指定一份现场已部署的 `inverter/` 目录，逐文件比对并报告差异。
    用于确认「只有预期内的文件发生变化」。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Clean `
        -VerifyAgainst "$env:TEMP\tenda_now\inverter"
#>
[CmdletBinding()]
param(
    [string]$OutDir,
    [switch]$Clean,
    [string]$VerifyAgainst
)

$ErrorActionPreference = "Stop"

$repoRoot   = Split-Path -Parent $PSScriptRoot
$srcRoot    = Join-Path $repoRoot "_g2src\hoymiles_g2"
$srcWww     = Join-Path $srcRoot "www"
$overlayDir = Join-Path $srcRoot "_packaged"

if (-not $OutDir) { $OutDir = Join-Path $repoRoot "dist\hoymiles" }
$invDir = Join-Path $OutDir "inverter"
$wwwDir = Join-Path $invDir "www"

function Step([string]$m) { Write-Host "[ .. ] $m" -ForegroundColor Cyan }
function Ok([string]$m)   { Write-Host "[ OK ] $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Fail([string]$m) { Write-Host "[FAIL] $m" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- helpers ---
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Read-Text([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-TextLf([string]$Path, [string]$Text) {
    # 仓库文本文件一律 LF（.gitattributes 亦如此约定），此处显式归一化。
    $t = $Text -replace "`r`n", "`n" -replace "`r", "`n"
    [System.IO.File]::WriteAllText($Path, $t, $Utf8NoBom)
}

function ConvertTo-Packaged([string]$Text) {
    $t = $Text -replace "`r`n", "`n" -replace "`r", "`n"
    # 子包比 parent 深一层：`from ..const` 指向 parent，`from .const` 指向自身。
    $t = $t -replace "from \.\.", "from ."
    $t = $t.Replace("/hoymiles_g2_static/", "/hoymiles_inverter_static/")
    return $t
}

# -------------------------------------------------------------- preflight ---
Step "预检"

if (-not (Test-Path $srcWww)) { Fail "找不到源目录：$srcWww" }

$manifestPath = Join-Path $srcRoot "manifest.json"
$srcVersion = "unknown"
if (Test-Path $manifestPath) {
    $srcVersion = (Read-Text $manifestPath | ConvertFrom-Json).version
}

# 形态结构性差异：只能来自覆盖目录，不做机械转换。
$overlayRequired = @("__init__.py", "const.py", "options_flow.py", "services.py", "region.py")
$transformSafe   = @(
    "binary_sensor.py", "coordinator.py", "discovery_override.py",
    "entity_gate.py", "keepalive.py", "lovelace.py",
    "mqtt_util.py", "number.py", "sensor.py"
)
# parent 拥有、子包不应携带的文件。
$parentOwned = @("config_flow.py", "manifest.json", "services.yaml", "strings.json")

# ---------------------------------------------------------------- prepare ---
if ($Clean -and (Test-Path $invDir)) {
    Step "清空 $invDir"
    Remove-Item $invDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $wwwDir | Out-Null

# --------------------------------------------------------------- frontend ---
Step "构建前端资源"
$jsCount = 0
$binCount = 0
foreach ($f in Get-ChildItem $srcWww -File) {
    $dest = Join-Path $wwwDir $f.Name
    if ($f.Extension -eq ".js") {
        Write-TextLf $dest (ConvertTo-Packaged (Read-Text $f.FullName))
        $jsCount++
    } else {
        Copy-Item $f.FullName $dest -Force
        $binCount++
    }
}
Ok "前端：$jsCount 个 js（已转换）+ $binCount 个二进制资源"

# ------------------------------------------------------------------ python ---
Step "构建后端模块"

$haveOverlay = Test-Path $overlayDir
$missingOverlay = @()

foreach ($name in $transformSafe) {
    $src = Join-Path $srcRoot $name
    if (-not (Test-Path $src)) { Warn "缺少 $name，跳过"; continue }
    Write-TextLf (Join-Path $invDir $name) (ConvertTo-Packaged (Read-Text $src))
}
Ok "转换安全模块：$($transformSafe.Count) 个"

foreach ($name in $overlayRequired) {
    $src = if ($haveOverlay) { Join-Path $overlayDir $name } else { $null }
    if ($src -and (Test-Path $src)) {
        Write-TextLf (Join-Path $invDir $name) (Read-Text $src)
    } else {
        $missingOverlay += $name
    }
}

if ($missingOverlay.Count -gt 0) {
    Warn "以下 $($missingOverlay.Count) 个文件在子包形态里是裁剪版，无法从独立形态机械生成："
    foreach ($n in $missingOverlay) { Write-Host "         - $n" -ForegroundColor Yellow }
    Warn "请把它们放入覆盖目录：$overlayDir"
    Warn "未生成这些文件时，产物不完整，**不可**整体部署；前端调试不受影响。"
} else {
    Ok "覆盖模块：$($overlayRequired.Count) 个（来自 _packaged/）"
}

foreach ($name in $parentOwned) {
    $stale = Join-Path $invDir $name
    if (Test-Path $stale) {
        Remove-Item $stale -Force
        Warn "移除 parent 拥有的 $name"
    }
}
foreach ($dir in @("brand", "translations")) {
    $stale = Join-Path $invDir $dir
    if (Test-Path $stale) { Remove-Item $stale -Recurse -Force; Warn "移除 parent 拥有的 $dir/" }
}

# ---------------------------------------------------------------- summary ---
Write-Host ""
Ok "产物：$invDir"
$total = (Get-ChildItem $invDir -Recurse -File | Measure-Object).Count
Write-Host "     文件总数 $total   （源版本 $srcVersion）"

# ---------------------------------------------------------------- verify ---
if ($VerifyAgainst) {
    Write-Host ""
    Step "与现场比对：$VerifyAgainst"
    if (-not (Test-Path $VerifyAgainst)) { Fail "比对目录不存在" }

    # 现场文件是 CRLF、构建产物是 LF，两者对 JS/Python 等价。
    # 因此按 EOL 归一化后的内容比对，否则换行符会把真实差异淹没。
    function Get-NormHash([string]$Path) {
        $t = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        $t = $t -replace "`r`n", "`n" -replace "`r", "`n"
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($t))
        return [System.BitConverter]::ToString($bytes)
    }

    $changed = @()
    $same = 0
    foreach ($f in Get-ChildItem $invDir -Recurse -File) {
        $rel = $f.FullName.Substring($invDir.Length + 1)
        $other = Join-Path $VerifyAgainst $rel
        if (-not (Test-Path $other)) { $changed += "新增  $rel"; continue }
        if ((Get-NormHash $f.FullName) -eq (Get-NormHash $other)) { $same++ }
        else { $changed += "变更  $rel" }
    }
    foreach ($f in Get-ChildItem $VerifyAgainst -Recurse -File) {
        if ($f.FullName -match "\\__pycache__\\") { continue }
        $rel = $f.FullName.Substring($VerifyAgainst.Length + 1)
        if (-not (Test-Path (Join-Path $invDir $rel))) { $changed += "缺失  $rel" }
    }

    Ok "未变化 $same 个文件"
    if ($changed.Count -eq 0) {
        Ok "与现场完全一致"
    } else {
        Write-Host "     差异 $($changed.Count) 项：" -ForegroundColor Yellow
        foreach ($c in $changed) { Write-Host "       $c" -ForegroundColor Yellow }
    }
}

Write-Host ""
