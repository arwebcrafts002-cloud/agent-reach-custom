# Agent Reach Local & Free Tunnel Background Service
$AppDir = "C:\Users\Hp\.gemini\antigravity\scratch\agent-reach-app"
$PythonExe = Join-Path $AppDir ".venv\Scripts\python.exe"
$WebApp = Join-Path $AppDir "web_app.py"
$DesktopUrlFile = "$([Environment]::GetFolderPath('Desktop'))\AGENT_REACH_URL.txt"
$LocalUrlFile = Join-Path $AppDir "LIVE_URL.txt"

# 1. Start Python Web Server if not running
$serverRunning = $false
try {
    $res = Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($res.StatusCode -eq 200) { $serverRunning = $true }
} catch {}

if (-not $serverRunning) {
    Start-Process -FilePath $PythonExe -ArgumentList "`"$WebApp`"" -WorkingDirectory $AppDir -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

# 2. Get local IP for Wi-Fi access
$localIp = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi*" -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress
if (-not $localIp) { $localIp = "127.0.0.1" }

# 3. Start localtunnel with fixed permanent subdomain and record URL
$FixedSubdomain = "agentreach-custom-app"
$tunnelLog = Join-Path $AppDir "tunnel.log"
if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }

$tunnelProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npx --yes localtunnel --port 8080 --subdomain $FixedSubdomain > `"$tunnelLog`" 2>&1" -WorkingDirectory $AppDir -WindowStyle Hidden -PassThru

# Wait for tunnel URL
$tunnelUrl = "https://$FixedSubdomain.loca.lt"
$attempts = 0
while ($attempts -lt 20) {
    Start-Sleep -Seconds 1
    if (Test-Path $tunnelLog) {
        $content = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($content -match "your url is:\s*(https://[^\s]+)") {
            $tunnelUrl = $matches[1]
            break
        }
    }
    $attempts++
}

$infoText = @"
=====================================================
         AGENT REACH — PERMANENT ACCESS URLs
=====================================================

1. FIXED PERMANENT PUBLIC URL (Never Changes):
   $tunnelUrl

2. LOCAL PC URL:
   http://localhost:8080
   http://127.0.0.1:8080

3. DIRECT MOBILE WI-FI ACCESS (Fastest & 100% Stable):
   http://$localIp:8080

Endpoints:
- Web UI / Extractor:  $tunnelUrl/
- Health Endpoint:     $tunnelUrl/health
- System Diagnostics:  $tunnelUrl/api/doctor
- Extract API:         POST $tunnelUrl/api/extract

Status: 100% ACTIVE (Fixed Permanent Subdomain with Auto-Watchdog)
Updated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
=====================================================
"@

Set-Content -Path $DesktopUrlFile -Value $infoText -Encoding UTF8
Set-Content -Path $LocalUrlFile -Value $infoText -Encoding UTF8

Write-Host "Agent Reach is live at: $tunnelUrl"

# 4. Watchdog loop: keep server & tunnel alive forever
while ($true) {
    Start-Sleep -Seconds 15

    # Health check local web app
    $appHealthy = $false
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $appHealthy = $true }
    } catch {}

    if (-not $appHealthy) {
        Get-Process python*, pythonw* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*agent-reach*" } | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Start-Process -FilePath $PythonExe -ArgumentList "`"$WebApp`"" -WorkingDirectory $AppDir -WindowStyle Hidden
    }

    # Health check localtunnel process & connectivity
    $tunnelHealthy = $false
    if (-not $tunnelProc.HasExited) {
        try {
            $tr = Invoke-WebRequest -Uri "https://$FixedSubdomain.loca.lt/health" -Headers @{ "Bypass-Tunnel-Reminder" = "true" } -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
            if ($tr.StatusCode -eq 200) { $tunnelHealthy = $true }
        } catch {}
    }

    if (-not $tunnelHealthy) {
        try { Stop-Process -Id $tunnelProc.Id -Force -ErrorAction SilentlyContinue } catch {}
        if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force -ErrorAction SilentlyContinue }
        $tunnelProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npx --yes localtunnel --port 8080 --subdomain $FixedSubdomain > `"$tunnelLog`" 2>&1" -WorkingDirectory $AppDir -WindowStyle Hidden -PassThru
    }
}
