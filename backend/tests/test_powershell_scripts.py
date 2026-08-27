import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required by this Windows project")
def test_runtime_scripts_are_valid_powershell() -> None:
    """A syntax error in setup or lifecycle scripts makes a fresh clone unusable."""
    paths = [ROOT / name for name in ("setup.ps1", "start.ps1", "stop.ps1", "restart.ps1")]
    paths.append(ROOT / "scripts" / "process-safety.ps1")
    command = """
    $failed = $false
    foreach ($path in $env:DOCUFLOW_SCRIPT_PATHS -split ';') {
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errors) | Out-Null
        if ($errors.Count -gt 0) { $failed = $true }
    }
    if ($failed) { exit 1 }
    """
    environment = os.environ | {"DOCUFLOW_SCRIPT_PATHS": ";".join(map(str, paths))}

    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required by this Windows project")
def test_process_guard_rejects_a_listener_from_another_project() -> None:
    """Starting DocuFlow must never stop or adopt an unrelated service on its ports."""
    command = """
    . $env:DOCUFLOW_PROCESS_HELPERS
    if (-not (Test-DocuFlowProcess -ProcessId $PID -Root $env:DOCUFLOW_PROJECT_ROOT)) { exit 10 }
    try {
        Assert-DocuFlowProcess -ProcessId $PID -Port 3000 -Root $env:DOCUFLOW_FOREIGN_ROOT
        exit 11
    } catch {
        if ($_.Exception.Message -notmatch 'another process') { exit 12 }
    }
    exit 0
    """
    # The executable directory is necessarily visible in this PowerShell's
    # command line, so it stands in for a project-owned uvicorn/vinext process.
    environment = os.environ | {
        "DOCUFLOW_PROCESS_HELPERS": str(ROOT / "scripts" / "process-safety.ps1"),
        "DOCUFLOW_PROJECT_ROOT": str(Path(POWERSHELL).parent),
        "DOCUFLOW_FOREIGN_ROOT": str(ROOT.parent / "a-project-that-is-not-running"),
    }

    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
