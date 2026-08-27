$runtime = Join-Path $PSScriptRoot ".runtime"
. (Join-Path $PSScriptRoot "scripts\process-safety.ps1")

foreach ($name in "backend", "frontend") {
    $pidFile = Join-Path $runtime "$name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidFile | Select-Object -First 1)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($process -and (Test-DocuFlowProcess -ProcessId $processId -Root $PSScriptRoot)) {
        Stop-Process -Id $processId
        Write-Host "$name stopped"
    } elseif ($process) {
        Write-Warning "$name was not stopped: the PID belongs to another project"
    }
    Remove-Item -LiteralPath $pidFile -Force
}
