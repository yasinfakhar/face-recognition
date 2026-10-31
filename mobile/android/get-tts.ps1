# Downloads what the app needs for KittenTTS voices (about 60 MB, not stored in git):
#   - sherpa-onnx 1.13.8 Android runtime (includes the espeak-ng phoneme converter)
#   - the KittenTTS v0.2 nano model
# Both come from https://github.com/k2-fsa/sherpa-onnx/releases. Run once before building:  .\get-tts.ps1
# Why not KittenTTS 0.8? Those models need sherpa-onnx 2.x, which removed espeak-ng.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$app = Join-Path $PSScriptRoot "app"
$base = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
$tmp = Join-Path ([IO.Path]::GetTempPath()) "facehello-tts"
New-Item -ItemType Directory -Force "$app\libs", "$app\src\main\assets\tts", $tmp | Out-Null

Write-Host "Downloading the sherpa-onnx runtime (37 MB)..."
Invoke-WebRequest "$base/v1.13.8/sherpa-onnx-static-link-onnxruntime-1.13.8.aar" -OutFile "$app\libs\sherpa-onnx-static-link-onnxruntime-1.13.8.aar" -UseBasicParsing

Write-Host "Downloading the KittenTTS nano model (25 MB)..."
Invoke-WebRequest "$base/tts-models/kitten-nano-en-v0_2-fp16.tar.bz2" -OutFile "$tmp\kitten.tar.bz2" -UseBasicParsing
tar -xjf "$tmp\kitten.tar.bz2" -C "$app\src\main\assets\tts"

Write-Host "Done. Now build the app (gradlew assembleDebug or Run in Android Studio)."
