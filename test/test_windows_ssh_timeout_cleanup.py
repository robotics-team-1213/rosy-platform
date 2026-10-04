"""Native Windows SSH timeout cleanup races, using each real helper body."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / 'deploy/robot/pinky_pro/verify'
HOSTS = [host for host in (shutil.which('powershell'), shutil.which('pwsh')) if host]


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(os.name != 'nt', reason='Windows native taskkill boundary')
@pytest.mark.parametrize('host', HOSTS)
@pytest.mark.parametrize('filename', ['verify-from-windows.ps1', 'validate-pinky-from-windows.ps1'])
@pytest.mark.parametrize('case', ['already_exited', 'still_running', 'silent_nonzero'])
def test_timeout_cleanup_preserves_classification_without_accepting_live_failure(tmp_path, host, filename, case):
    source = VERIFY / filename
    launch_marker = tmp_path / 'launches.txt'
    owned_marker = tmp_path / 'owned-pid.txt'
    child = tmp_path / 'benign_child.py'
    child.write_text('from pathlib import Path\nimport sys,time\n'
                     'with Path(sys.argv[1]).open("a") as f: f.write("started\\n")\n'
                     'time.sleep(6)\n', encoding='utf-8')
    silent = tmp_path / 'silent-fail.cmd'
    silent.write_bytes(b'@echo off\r\nexit /b 1\r\n')
    call = '& taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null'
    marker = '[IO.File]::WriteAllText(' + ps_quote(owned_marker) + ', [string]$process.Id)\n'
    if case == 'already_exited':
        injected = (marker + '& $nativeTaskkill /PID $process.Id /T /F *> $null\n'
                    'if (-not $process.WaitForExit(5000)) { throw "fixture child did not exit" }\n' + call)
    elif case == 'still_running':
        injected = marker + '& taskkill.exe /PID -999999999 /T /F 2>&1 | Out-Null'
    else:
        injected = marker + '& ' + ps_quote(silent) + ' 2>&1 | Out-Null'
    launcher = tmp_path / 'race.ps1'
    script = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$nativeTaskkill = Join-Path $env:SystemRoot 'System32/taskkill.exe'
$parseTokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(SOURCE, [ref]$parseTokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'source parse failed' }
$functions = @($ast.FindAll({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-BoundedSshProcess'
}, $true))
if ($functions.Count -ne 1) { throw 'expected exactly one real helper' }
$body = $functions[0].Extent.Text
$call = CALL
if (($body.Split(@($call), [StringSplitOptions]::None)).Count -ne 2) { throw 'expected one native kill call' }
$body = $body.Replace($call, INJECTED)
Invoke-Expression $body
$report = [ordered]@{raised=$false;result=$null;error=$null;owned_pid_exited=$false}
try {
    $invokeArguments = @{
        Executable = PYTHON
        Arguments = @(CHILD, LAUNCH)
        TimeoutSec = 2
        ScratchDirectory = SCRATCH
    }
    $report.result = Invoke-BoundedSshProcess @invokeArguments
}
catch {
    $report.raised = $true
    $report.error = $_.Exception.Message
}
finally {
    if (Test-Path -LiteralPath OWNED) {
        $ownedProcessId = [int]([IO.File]::ReadAllText(OWNED))
        try { & $nativeTaskkill /PID $ownedProcessId /T /F *> $null } catch { }
        try {
            $remaining = Get-Process -Id $ownedProcessId -ErrorAction Stop
            $report.owned_pid_exited = $remaining.WaitForExit(5000)
        }
        catch { $report.owned_pid_exited = $true }
    }
}
$report | ConvertTo-Json -Depth 5 -Compress
"""
    values = {'SOURCE': source, 'CALL': call, 'INJECTED': injected, 'PYTHON': sys.executable,
              'CHILD': child, 'LAUNCH': launch_marker, 'SCRATCH': tmp_path, 'OWNED': owned_marker}
    # Tokens are uppercase placeholders, not shell interpolation.
    for token, value in values.items():
        script = script.replace(token, ps_quote(value))
    launcher.write_text(script, encoding='utf-8')
    result = subprocess.run([host, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(launcher)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip())
    assert owned_marker.is_file(), 'fixture must exercise actual timeout cleanup'
    assert report['owned_pid_exited'], 'only the tracked fixture process/tree is cleaned up'
    assert launch_marker.read_text().splitlines() == ['started'], 'no replay or second SSH child launch'
    if case == 'already_exited':
        assert report['raised'] is False, report['error']
        assert report['result']['TimedOut'] is True
        assert report['result']['ExitCode'] is None
        assert report['result']['Output'] == ''
    else:
        assert report['raised'] is True, 'a live cleanup failure must propagate instead of waiting or succeeding'
        assert report['result'] is None
