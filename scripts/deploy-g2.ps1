# Deploy _g2src/hoymiles_g2 to HA over SSH
# Requires: ssh-keygen, HA add-on core_ssh enabled
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\deploy-g2.ps1

$ErrorActionPreference = "Stop"

$HA     = "192.168.31.99"
$KEY    = Join-Path $env:TEMP "ha_deploy_ed25519"
$SRC    = Join-Path $PSScriptRoot "..\_g2src\hoymiles_g2"
$DEST   = "/config/custom_components/hoymiles_g2"

function Ok([string]$m)   { Write-Host "[ OK ] $m" -ForegroundColor Green }
function Step([string]$m) { Write-Host "[ .. ] $m" -ForegroundColor Cyan }

# --- 1. temp key -------------------------------------------------------------
if (-not (Test-Path $KEY)) {
    Step "generating temp key"
    ssh-keygen -t ed25519 -N '""' -f $KEY -C "ha-deploy-tmp" | Out-Null
}
$Pub = Get-Content "$KEY.pub" -Raw

# --- 2. find the SSH addon slug ---------------------------------------------
Step "locating SSH addon"
$addons = (curl.exe -s -H "Authorization: Bearer $env:HA_TOKEN" "http://$HA/api/hassio/addons") 2>$null
if (-not $addons) {
    Write-Host "Set HA_TOKEN to a long-lived access token first." -ForegroundColor Red
    exit 1
}
$slug = ($addons | ConvertFrom-Json).data.addons |
    Where-Object { $_.slug -match 'ssh' } | Select-Object -First 1 -ExpandProperty slug
Ok "addon: $slug"

# --- 2.5. snapshot existing authorized_keys ----------------------------------
Step "reading current authorized_keys"
$origKeys = @()
try {
    $optsJson = (curl.exe -s -H "Authorization: Bearer $env:HA_TOKEN" `
        "http://$HA/api/hassio/addons/$slug/options") 2>$null
    if ($optsJson) {
        $optsData = ($optsJson | ConvertFrom-Json).data
        $origKeys = @($optsData.options.authorized_keys)
    }
} catch { }
if ($origKeys.Count -gt 0) {
    Ok ("snapshot: " + $origKeys.Count + " key(s)")
} else {
    Ok "no existing keys (or unreadable)"
}

# --- 3. inject the key, restart, deploy, restore ----------------------------
Step "injecting key"
$body = @{ options = @{ authorized_keys = @($Pub) } } | ConvertTo-Json -Depth 5
curl.exe -s -X POST -H "Authorization: Bearer $env:HA_TOKEN" `
    -H "Content-Type: application/json" -d $body `
    "http://$HA/api/hassio/addons/$slug/options" | Out-Null

curl.exe -s -X POST -H "Authorization: Bearer $env:HA_TOKEN" `
    "http://$HA/api/hassio/addons/$slug/restart" | Out-Null

Step "waiting for ssh"
$ready = $false
foreach ($i in 1..30) {
    ssh -F NUL -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=3 `
        "root@$HA" "echo ok" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Host "SSH never came up" -ForegroundColor Red; exit 1 }
Ok "ssh ready"

Step "copying files"
ssh -F NUL -i $KEY -o StrictHostKeyChecking=no "root@$HA" "mkdir -p $DEST"
scp -F NUL -i $KEY -o StrictHostKeyChecking=no -r "$SRC\*" "root@$HA`:$DEST/"

Step "restarting Home Assistant core"
ssh -F NUL -i $KEY -o StrictHostKeyChecking=no "root@$HA" "ha core restart" | Out-Null

Step "restoring authorized_keys"
$restoreKeys = $origKeys
if ($restoreKeys.Count -eq 0) {
    # Fall back to the known single admin key rather than wiping SSH access.
    $restoreKeys = @("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFL8Obipx/jfJiLtOFU06P609C4dbRt5zFlkOvBi5kuu qiyang.lin@hoymiles.com")
}
$restoreBody = @{ options = @{ authorized_keys = @($restoreKeys) } } | ConvertTo-Json -Depth 5
curl.exe -s -X POST -H "Authorization: Bearer $env:HA_TOKEN" `
    -H "Content-Type: application/json" -d $restoreBody `
    "http://$HA/api/hassio/addons/$slug/options" | Out-Null

Remove-Item $KEY, "$KEY.pub" -ErrorAction SilentlyContinue
Ok "deployed"
