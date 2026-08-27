param([switch]$OpenBrowser)

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtime = Join-Path $projectRoot ".runtime"
$backend = Join-Path $projectRoot "backend"
. (Join-Path $projectRoot "scripts\process-safety.ps1")

# A clone that has never been set up is the common case on a new machine, and
# the failure it produces otherwise is a stack trace from whichever step got
# furthest. Name the missing piece instead.
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. Run .\setup.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "node_modules"))) {
    throw "Node dependencies are not installed. Run .\setup.ps1 first."
}

New-Item -ItemType Directory -Path $runtime -Force | Out-Null

$lms = Get-Command lms -ErrorAction SilentlyContinue
if ($lms) {
    $serverStatus = & $lms.Source server status 2>&1
    if ($serverStatus -match "not running") {
        & $lms.Source server start --port 1234 | Out-Null
    }
}

function Test-BuildIsStale {
    <#
        Whether the frontend on disk was built from the source now on disk.

        `npm run start` serves dist/ and never looks at the source again, so a
        `git pull` that changes the app leaves the old bundle being served with
        nothing to say so: the pages look right, they are just last week's. The
        build output is compared against the newest source file rather than
        rebuilt every time, because a rebuild costs half a minute.
    #>
    param([string]$Root)

    $built = Join-Path $Root "dist\server\index.js"
    if (-not (Test-Path -LiteralPath $built)) { return $true }
    $builtAt = (Get-Item -LiteralPath $built).LastWriteTimeUtc

    $sources = @()
    foreach ($folder in @("app", "lib", "public")) {
        $path = Join-Path $Root $folder
        if (Test-Path -LiteralPath $path) {
            $sources += Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue
        }
    }
    foreach ($file in @("package.json", "package-lock.json", "next.config.ts", "vite.config.ts", "tsconfig.json")) {
        $path = Join-Path $Root $file
        if (Test-Path -LiteralPath $path) { $sources += Get-Item -LiteralPath $path }
    }
    if (-not $sources) { return $false }

    $newest = ($sources | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc
    return $newest -gt $builtAt
}

$backendPid = Get-ListenerProcessId 8000
if ($backendPid) {
    Assert-DocuFlowProcess -ProcessId $backendPid -Port 8000 -Root $projectRoot
} else {
    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $backend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtime "backend.out.log") `
        -RedirectStandardError (Join-Path $runtime "backend.err.log")
}

# A build that landed under the running server leaves it importing chunk
# names that no longer exist. Sometimes that is a 500, but more often the page
# itself still renders and only its scripts 404: the browser shows the first
# screen, no navigation works, and nothing looks broken. Recover instead of
# leaving someone clicking a dead sidebar.
$frontendPid = Get-ListenerProcessId 3000
if ($frontendPid) {
    # A listener is not proof that DocuFlow owns the port. In particular, do
    # not probe and then terminate another application's development server.
    Assert-DocuFlowProcess -ProcessId $frontendPid -Port 3000 -Root $projectRoot
    try {
        $probe = Invoke-WebRequest "http://localhost:3000" -UseBasicParsing -TimeoutSec 15
        $healthy = $probe.StatusCode -eq 200
        if ($healthy) {
            # A 200 on the page is not enough. The server keeps the manifest of
            # the build it started with, so it can name chunks that a later
            # build has already replaced. Ask for each one.
            $chunks = [regex]::Matches($probe.Content, '_next/static/chunks/[A-Za-z0-9_\-]+\.js') |
                ForEach-Object { $_.Value } |
                Select-Object -Unique
            if (-not $chunks) { $healthy = $false }
            foreach ($chunk in $chunks) {
                try {
                    $asset = Invoke-WebRequest "http://localhost:3000/$chunk" -UseBasicParsing -TimeoutSec 15
                    if ($asset.StatusCode -ne 200) { $healthy = $false }
                } catch {
                    $healthy = $false
                }
            }
        }
    } catch {
        $healthy = $false
    }
    if (-not $healthy) {
        Write-Host "The running frontend cannot serve its own build. Rebuilding..."
        # Only the frontend. stop.ps1 takes the backend down too, and the block
        # that starts the backend has already run and found it healthy, so
        # stopping it here would leave it down for the rest of this run.
        Stop-Process -Id $frontendPid -Force -ErrorAction SilentlyContinue
        for ($attempt = 0; $attempt -lt 20 -and (Get-ListenerProcessId 3000); $attempt++) {
            Start-Sleep -Milliseconds 250
        }
        if (Get-ListenerProcessId 3000) {
            throw "The DocuFlow frontend did not release port 3000."
        }
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

if (-not (Get-ListenerProcessId 3000)) {
    if (Test-BuildIsStale -Root $projectRoot) {
        Write-Host "The frontend build is older than the source. Rebuilding..."
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
        $listenerPid = Get-ListenerProcessId $service.Port
    }
    if (-not $listenerPid) { throw "$($service.Name) did not start on port $($service.Port)" }
    Assert-DocuFlowProcess -ProcessId $listenerPid -Port $service.Port -Root $projectRoot
    $listenerPid | Set-Content -LiteralPath (Join-Path $runtime "$($service.Name).pid")
}

Write-Host "DocuFlow is starting: http://localhost:3000"
Write-Host "To stop it: .\stop.ps1"

if ($OpenBrowser) {
    Start-Process "http://localhost:3000"
}
