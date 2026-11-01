# Deploys the integration into the local Home Assistant test container and restarts it.
# Usage: powershell -File scripts\deploy.ps1 [-Container homeassistant-test] [-NoRestart]
param(
    [string]$Container = "homeassistant-test",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "custom_components\pill_reminder"
$target = "/config/custom_components/pill_reminder"

Write-Host "Copying $source -> ${Container}:$target"
docker exec $Container rm -rf $target
docker exec $Container mkdir -p /config/custom_components
docker cp $source "${Container}:/config/custom_components/"
docker exec $Container sh -c "find $target -name __pycache__ -type d -prune -exec rm -rf {} +"

if ($NoRestart) { return }

Write-Host "Restarting $Container ..."
$since = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
docker restart $Container | Out-Null

# Wait until HA answers on port 8123 (max. 120 s)
$deadline = (Get-Date).AddSeconds(120)
do {
    Start-Sleep -Seconds 3
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:8123/manifest.json" -UseBasicParsing -TimeoutSec 3
        $up = $true
    } catch { $up = $false }
} until ($up -or (Get-Date) -gt $deadline)

Write-Host ("Home Assistant is " + ($(if ($up) { "up" } else { "NOT reachable" })))
Write-Host "--- Log lines mentioning pill_reminder ---"
$ErrorActionPreference = "Continue"
cmd /c "docker logs --since $since $Container 2>&1" | Select-String -Pattern "pill_reminder"
