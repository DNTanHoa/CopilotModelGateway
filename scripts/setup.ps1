[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

Write-Host "Copilot Model Gateway setup" -ForegroundColor Cyan
Write-Host "Root: $Root"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ was not found on PATH. Install Python, then run setup again."
}

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    & python -m venv $Venv
}

Write-Host "Upgrading packaging tools..." -ForegroundColor Yellow
& $Python -m pip install --upgrade pip setuptools wheel

Write-Host "Installing gateway and development tools..." -ForegroundColor Yellow
& $Python -m pip install -e "$Root[dev]"

Push-Location $Root
try {
    & $Python -m copilot_model_gateway --root $Root init
    & $Python -m copilot_model_gateway --root $Root doctor
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Setup completed." -ForegroundColor Green
Write-Host "Next: edit .env and config\gateway.yaml, then run .\gateway.ps1 start"
