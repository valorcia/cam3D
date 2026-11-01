# cam3D - installation développeur Windows 11 (PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# NON TESTÉ sur une machine Windows réelle à ce stade (voir INSTALLATION.md) :
# le script suit les distributions officielles et s'arrête avec un message clair
# si un outil manque, il ne télécharge aucun exécutable automatiquement.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "Python 3.10+ requis : https://www.python.org/downloads/windows/"; exit 1 }
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
& ".venv\Scripts\python.exe" -m pip install -q -e "backend[dev]"
Write-Host ""
Write-Host "==> Outils externes"
if (-not $env:CAM3D_OPENMVS_DIR -and -not (Test-Path "third_party\openmvs\bin\DensifyPointCloud.exe")) {
  Write-Host "OpenMVS absent : téléchargez l'archive Windows officielle (https://github.com/cdcseacave/openMVS/releases, v2.3.0),"
  Write-Host "décompressez-la dans third_party\openmvs\ (ou définissez CAM3D_OPENMVS_DIR)."
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Host "FFmpeg absent (import vidéo) : https://ffmpeg.org/download.html" }
& ".venv\Scripts\cam3d.exe" doctor
