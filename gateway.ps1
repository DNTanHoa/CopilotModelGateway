[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "init", "doctor", "models", "render", "start", "test")]
    [string]$Command = "doctor",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupScript = Join-Path $Root "scripts\setup.ps1"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if ($Command -eq "setup") {
    & $SetupScript
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run: .\gateway.ps1 setup"
}

Push-Location $Root
try {
    & $Python -m copilot_model_gateway --root $Root $Command @CommandArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
