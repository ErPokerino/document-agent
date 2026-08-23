param([switch]$OpenBrowser)

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtime = Join-Path $projectRoot ".runtime"
$backend = Join-Path $projectRoot "backend"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. Run first: python -m venv .venv"
}

New-Item -ItemType Directory -Path $runtime -Force | Out-Null

$lms = Get-Command lms -ErrorAction SilentlyContinue
if ($lms) {
    $serverStatus = & $lms.Source server status 2>&1
    if ($serverStatus -match "not running") {
        & $lms.Source server start --port 1234 | Out-Null
    }
}

function Get-ListenerPid([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return $listener.OwningProcess
}

if (-not (Get-ListenerPid 8000)) {
    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $backend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtime "backend.out.log") `
        -RedirectStandardError (Join-Path $runtime "backend.err.log")
}

# A build that landed under the running server leaves it importing chunk
# names that no longer exist, and every page becomes a 500. `npm test` runs a
# build, so this is one `npm test` away at any time: recover instead of
# leaving someone to read a stack trace.
$frontendPid = Get-ListenerPid 3000
if ($frontendPid) {
    try {
        $probe = Invoke-WebRequest "http://localhost:3000" -UseBasicParsing -TimeoutSec 15
        $healthy = $probe.StatusCode -eq 200
    } catch {
        $healthy = $false
    }
    if (-not $healthy) {
        Write-Host "The running frontend cannot serve its own build. Rebuilding..."
        & (Join-Path $projectRoot "stop.ps1") | Out-Null
        Push-Location $projectRoot
        try {
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
        }
        finally {
            Pop-Location
        }
    }
}

if (-not (Get-ListenerPid 3000)) {
    # `npm run start` serves dist/ and never builds it, so a fresh clone would
    # otherwise fail with an empty output directory.
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "dist\server\index.js"))) {
        Write-Host "Building the frontend (first run)..."
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
    }

    Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "start" -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtime "frontend.out.log") `
        -RedirectStandardError (Join-Path $runtime "frontend.err.log")
}

foreach ($service in @(@{ Name = "backend"; Port = 8000 }, @{ Name = "frontend"; Port = 3000 })) {
    $listenerPid = $null
    for ($attempt = 0; $attempt -lt 30 -and -not $listenerPid; $attempt++) {
        Start-Sleep -Milliseconds 500
        $listenerPid = Get-ListenerPid $service.Port
    }
    if (-not $listenerPid) { throw "$($service.Name) did not start on port $($service.Port)" }
    $listenerPid | Set-Content -LiteralPath (Join-Path $runtime "$($service.Name).pid")
}

Write-Host "DocuFlow is starting: http://localhost:3000"
Write-Host "To stop it: .\stop.ps1"

if ($OpenBrowser) {
    Start-Process "http://localhost:3000"
}
