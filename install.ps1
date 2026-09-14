[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "ClayFarmControl\0.3.0.dev1"),
    [switch]$Apply
)
$ErrorActionPreference = "Stop"
$Source = $PSScriptRoot
& $Python -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required." }
if (Test-Path -LiteralPath $InstallDir) { throw "Refusing to overwrite existing path: $InstallDir" }
Write-Host "Source: $Source"
Write-Host "New isolated environment: $InstallDir"
Write-Host "Requires network for pip; no models or credentials are installed."
if (-not $Apply) { Write-Host "Plan only. Add -Apply to install."; exit 0 }
$Parent = Split-Path -Parent $InstallDir
New-Item -ItemType Directory -Force -Path $Parent | Out-Null
& $Python -m venv $InstallDir
if ($LASTEXITCODE -ne 0) { throw "venv creation failed; original installation untouched." }
$VenvPython = Join-Path $InstallDir 'Scripts\python.exe'
$Cli = Join-Path $InstallDir 'Scripts\clayfarm.exe'
& $VenvPython -m pip install "${Source}[test]"
if ($LASTEXITCODE -ne 0) { throw "Package installation failed; inspect this isolated directory." }
& $Cli --version
if ($LASTEXITCODE -ne 0) { throw "CLI verification failed." }
Write-Host "Installed command: $Cli"
Write-Host "Run: & '$Cli' setup --server https://YOUR-APPROVED-SERVER --role both"
