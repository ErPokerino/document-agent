<#
    One command to make a fresh clone runnable.

    Everything under backend/data is ignored by git, so a checkout arrives with
    no settings, no database and no credentials. That part is deliberate: it is
    where API keys and real invoices live. This script builds what can be built
    automatically and then says plainly what only a person can supply.

    Safe to run again: every step checks before it acts.
#>

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Invoke-Native {
    <#
        Run an external tool and judge it by its exit code.

        Native tools write progress and warnings to stderr as a matter of
        course — the frontend build prints a plugin timing note there on every
        successful run. With $ErrorActionPreference = "Stop" PowerShell turns
        each of those lines into a terminating error, so the script fails while
        the tool it ran succeeded. The exit code is the only thing that says
        what actually happened.
    #>
    param(
        [Parameter(Mandatory)][scriptblock]$Command,
        [Parameter(Mandatory)][string]$WhatFailed
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw $WhatFailed }
}

function Require-Command([string]$Name, [string]$Hint) {
    $found = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $found) { throw "$Name was not found on PATH. $Hint" }
    return $found
}

Write-Host "Checking prerequisites..."
Require-Command "python" "Install Python 3.11 or newer from python.org." | Out-Null
Require-Command "npm" "Install Node.js 22 or newer from nodejs.org." | Out-Null

$nodeVersion = [version]((& node --version) -replace "^v", "")
$minimumNodeVersion = [version]"22.13.0"
if ($nodeVersion -lt $minimumNodeVersion) {
    throw "Node.js $nodeVersion is too old. This project needs 22.13.0 or newer."
}
$pythonVersion = (& python --version) -replace "^Python ", ""
$pythonParts = $pythonVersion -split "\."
if ([int]$pythonParts[0] -lt 3 -or ([int]$pythonParts[0] -eq 3 -and [int]$pythonParts[1] -lt 11)) {
    throw "Python $pythonVersion is too old. This project needs 3.11 or newer."
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Creating the Python environment..."
    Invoke-Native { & python -m venv (Join-Path $projectRoot ".venv") } "Could not create .venv"
}

Write-Host "Installing Python dependencies..."
Invoke-Native { & $python -m pip install --quiet --upgrade pip } "pip could not update itself"
Invoke-Native {
    & $python -m pip install --quiet -r (Join-Path $projectRoot "backend\requirements.lock.txt")
} "Python dependencies failed to install"

Write-Host "Installing Node dependencies..."
Push-Location $projectRoot
try {
    # package-lock.json is the cross-machine contract. `npm install` is allowed
    # to rewrite it and can silently select a newer transitive dependency.
    Invoke-Native { & npm.cmd ci } "npm ci failed"
    Write-Host "Building the frontend..."
    Invoke-Native { & npm.cmd run build } "Frontend build failed"
}
finally { Pop-Location }

New-Item -ItemType Directory -Path (Join-Path $projectRoot "backend\data") -Force | Out-Null

# What no script can do for you. Stated as a list of facts, not as a warning:
# each one is optional depending on which pipelines you intend to run.
Write-Host ""
Write-Host "Setup finished. Start the app with: .\start.ps1 -OpenBrowser"
Write-Host ""
Write-Host "Still to do by hand, depending on what you want to run:"

$lms = Get-Command lms -ErrorAction SilentlyContinue
if ($lms) {
    Write-Host "  [ok]   LM Studio CLI found. DocuFlow reads this machine's hardware through it."
} else {
    Write-Host "  [todo] LM Studio is not on PATH. Install it and run 'lms bootstrap' to use local models."
}

$credentials = Join-Path $projectRoot "backend\data\gcp-service-account.json"
if (Test-Path -LiteralPath $credentials) {
    Write-Host "  [ok]   Document AI service-account key is in place."
} else {
    Write-Host "  [todo] For the Document AI pipelines - OCR, Layout Parser and the Custom"
    Write-Host "         Extractor - save a Google service-account key as"
    Write-Host "         backend\data\gcp-service-account.json, then fill in the project and"
    Write-Host "         processor ids under Settings."
}

Write-Host "  [todo] For the hosted models, paste a Gemini API key under LLM. It is stored in"
Write-Host "         backend\data\settings.json on this machine and never sent to the browser."
Write-Host "  [todo] Choose a model under LLM. A fresh install has none selected, because which"
Write-Host "         models exist depends on this machine."
