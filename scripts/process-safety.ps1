function Get-ListenerProcessId([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    return $listener.OwningProcess
}

function Test-DocuFlowProcess {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [Parameter(Mandatory)][string]$Root
    )

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $process -or -not $process.CommandLine) { return $false }
    return $process.CommandLine.IndexOf($Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Assert-DocuFlowProcess {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string]$Root
    )

    if (-not (Test-DocuFlowProcess -ProcessId $ProcessId -Root $Root)) {
        throw "Port $Port is already used by another process (PID $ProcessId). DocuFlow was not started."
    }
}
