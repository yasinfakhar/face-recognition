# Optional laptop shortcut: (re)starts face recognition on the phone over USB and opens the viewer.
# The phone can also do this by itself: open Termux and run  bash /sdcard/FaceHello/run.sh
# Requirements: phone connected by USB (USB debugging on), unlocked, on the same Wi-Fi as this PC.
$ErrorActionPreference = "Stop"
$here = Join-Path (Split-Path $PSScriptRoot -Parent) "phone"   # the files that live on the phone
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
if (-not $adb) { $adb = "C:\platform-tools\adb.exe" }
function A { & $adb @args }

function Test-Url($url) {
    try { (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200 } catch { $false }
}

if (-not ((A devices) -match "`tdevice$")) {
    Write-Host "No phone found. Plug it in, unlock it and accept the USB debugging prompt." -ForegroundColor Red
    exit 1
}

$ipInfo = (A shell ip -f inet addr show wlan0) -join " "
if ($ipInfo -notmatch "inet (\d+\.\d+\.\d+\.\d+)") {
    Write-Host "The phone has no Wi-Fi address. Connect it to Wi-Fi." -ForegroundColor Red
    exit 1
}
$ip = $Matches[1]
Write-Host "Phone address: $ip"

Write-Host "Copying the latest files to the phone..."
A shell mkdir -p /sdcard/FaceHello/faces | Out-Null
foreach ($f in "facehello.py", "viewer.html", "run.sh") { A push "$here\$f" /sdcard/FaceHello/ | Out-Null }

A shell input keyevent KEYCODE_WAKEUP | Out-Null
Write-Host "Starting face recognition in Termux..."
A shell am force-stop com.termux | Out-Null
A shell am force-stop com.pas.webcam.pro | Out-Null   # the camera must be free
Start-Sleep 2
A shell monkey -p com.termux -c android.intent.category.LAUNCHER 1 | Out-Null
Start-Sleep 4
A shell "input text 'clear;bash%s/sdcard/FaceHello/run.sh'" | Out-Null
A shell input keyevent 66 | Out-Null

$ready = $false
foreach ($i in 1..20) {
    Start-Sleep 2
    if (Test-Url "http://${ip}:8081/status.json") { $ready = $true; break }
}
if (-not $ready) {
    Write-Host "Recognition did not come up. Look at the Termux screen on the phone for errors." -ForegroundColor Red
    exit 1
}

Write-Host "Ready. Opening the viewer..." -ForegroundColor Green
cmd /c start "" "http://${ip}:8081"
