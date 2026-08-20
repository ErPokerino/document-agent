param([switch]$OpenBrowser)

# Build and restart as one step.
#
# `vinext start` loads dist/server/index.js once, at startup, and the HTML it
# serves names client chunks by content hash. Rebuilding under a running server
# leaves it serving hashes that no longer exist on disk: every asset 404s or
# comes back empty, React never hydrates, and the page looks fine while every
# click does nothing. Restarting without rebuilding has the mirror problem.
#
# Note that `npm test` runs a build, so re-run this afterwards.

$projectRoot = $PSScriptRoot

& (Join-Path $projectRoot "stop.ps1")

Push-Location $projectRoot
try {
    Write-Host "Building the frontend..."
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
}
finally {
    Pop-Location
}

& (Join-Path $projectRoot "start.ps1") -OpenBrowser:$OpenBrowser
