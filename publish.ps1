[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root "scripts\publish-to-github.ps1")
exit $LASTEXITCODE
