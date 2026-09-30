param(
    [Parameter(Mandatory = $true)][ValidatePattern('^rosy-pinky-[a-hj-km-np-z2-9]{4}$')][string]$DeviceName,
    [Parameter(Mandatory = $true)][ValidatePattern('^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$')][string]$RobotAddress,
    [string]$SshHost = $DeviceName,
    [switch]$OperatorPresent,
    [switch]$PowerCutReady,
    [switch]$CheckOnly,
    [string]$RosyUser = 'rosy',
    [string]$KeyPath = '',
    [string]$KnownHosts = '',
    [switch]$PrintSshArguments
)

# This is the operator-attended continuation after first boot. It prepares the
# G4 motor runtime but never releases E-Stop or sends a nonzero velocity.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# D-385 (6): the same Rosy operator key and known_hosts as rosy-release-push.ps1.
# 2026-10-01 a new card failed with "No ED25519 host key is known" because only
# the default ~/.ssh alias was used. Host-key checking stays strict.
if (-not $KeyPath) { $KeyPath = Join-Path $env:LOCALAPPDATA 'Rosy\ssh\rosy-operator-ed25519' }
if (-not $KnownHosts) { $KnownHosts = Join-Path $env:LOCALAPPDATA 'Rosy\known_hosts' }
$KeyPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($KeyPath)
$KnownHosts = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($KnownHosts)
if ($RosyUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw 'Invalid Rosy user name.' }
$script:sshOptions = @('-i', $KeyPath, '-o', 'IdentitiesOnly=yes', '-o', ('UserKnownHostsFile=' + $KnownHosts),
    '-l', $RosyUser, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5')
if ($PrintSshArguments) {
    [pscustomobject]@{ ssh_host = $SshHost; ssh_options = $script:sshOptions } | ConvertTo-Json -Compress
    return
}
foreach ($required in @(@('operator key', $KeyPath), @('known_hosts', $KnownHosts))) {
    if (-not (Test-Path -LiteralPath $required[1] -PathType Leaf)) {
        throw ("The Rosy {0} file is missing: {1} (pass -KeyPath / -KnownHosts)." -f $required[0], $required[1])
    }
}

if (-not $CheckOnly -and (-not $OperatorPresent -or -not $PowerCutReady)) {
    throw 'A present operator and immediate physical power cut are required.'
}
if ($SshHost -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]{0,62}$') {
    throw 'Invalid SSH host alias.'
}
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($RobotAddress, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'RobotAddress must be an IPv4 address.'
}

$credentialPath = Join-Path $env:LOCALAPPDATA ("Rosy\api\{0}.credential.xml" -f $DeviceName)
$credential = Import-Clixml -LiteralPath $credentialPath
$token = $credential.GetNetworkCredential().Password
if ([string]::IsNullOrWhiteSpace($token)) { throw 'CORE credential is empty.' }
$headers = @{ Authorization = 'Bearer ' + $token }
$baseUrl = 'http://' + $RobotAddress + ':8080'

function Get-Core([string]$path) {
    Invoke-RestMethod -Uri ($baseUrl + $path) -Headers $headers -TimeoutSec 5 -ErrorAction Stop
}
function Stop-CoreMotion {
    Invoke-RestMethod -Uri ($baseUrl + '/api/v1/safety/stop') -Method Post -Headers $headers `
        -ContentType 'application/json' -Body '{}' -TimeoutSec 5 -ErrorAction Stop | Out-Null
}
function Invoke-RobotSsh([string]$command) {
    $output = & ssh.exe @script:sshOptions $SshHost $command 2>&1
    if ($LASTEXITCODE -ne 0) { throw ("SSH command failed: {0}" -f ($output -join ' ')) }
    return $output
}
function Invoke-RobotPython([string]$script) {
    $output = $script | & ssh.exe @script:sshOptions $SshHost 'sudo -n python3 -' 2>&1
    if ($LASTEXITCODE -ne 0) { throw ("Robot configuration failed: {0}" -f ($output -join ' ')) }
}

$info = Get-Core '/api/v1/system/info'
if ($info.robot_name -cne $DeviceName -or $info.robot_id -notmatch '^rosy_[0-9]+$') {
    throw 'CORE identity does not match the requested device.'
}
$complete = (Invoke-RobotSsh 'sudo -n cat /var/lib/rosy/provisioning/complete.json') -join "`n" | ConvertFrom-Json
$state = (Invoke-RobotSsh 'sudo -n cat /var/lib/rosy/provisioning/state.json') -join "`n" | ConvertFrom-Json
if ($state.state -cne 'PROVISIONED' -or $complete.device_name -cne $DeviceName -or
    $complete.dds.namespace -cne $info.ros_namespace -or
    [int]$complete.dds.robot_number -ne [int]$info.robot_number) {
    throw 'First-boot provisioning and CORE readback do not agree.'
}
$uid = [string]$complete.device_uid
if ($uid -notmatch '^[0-9a-f-]{36}$') { throw 'Invalid device UID.' }
$runtimeLines = @(Invoke-RobotSsh 'sudo -n cat /etc/rosy/runtime.env')
$runtimeText = ($runtimeLines -join "`n") + "`n"
if ($runtimeText -notmatch [regex]::Escape("ROSY_DEVICE_UID=$uid")) {
    throw 'Runtime device UID does not match provisioning.'
}
if ($CheckOnly) {
    [pscustomobject]@{ device_name = $DeviceName; device_uid = $uid;
        robot_id = $info.robot_id; runtime_mode = $info.runtime_mode;
        provisioning = $state.state; changed = $false } | ConvertTo-Json -Compress
    return
}

$evidenceDir = Join-Path 'X:\DevTemp' ("rosy-motor-{0}-{1}" -f $DeviceName, (Get-Date -Format 'yyyyMMddTHHmmssfff'))
New-Item -ItemType Directory -Path $evidenceDir -ErrorAction Stop | Out-Null
[IO.File]::WriteAllText((Join-Path $evidenceDir 'runtime.before.env'), $runtimeText,
    [Text.UTF8Encoding]::new($false))
$changed = $false
$ioStopped = $false
try {
    Stop-CoreMotion
    $safety = Get-Core '/api/v1/safety/state'
    if (-not $safety.estop) { throw 'E-Stop did not latch.' }

    if ($info.runtime_mode -ceq 'core') {
        if ($runtimeText -notmatch '(?m)^ROSY_RUNTIME_MODE=core$' -or
            $runtimeText -match '(?m)^ROSY_IO_DRIVE_ENABLED=') {
            throw 'Unexpected initial runtime settings.'
        }
        Invoke-RobotSsh 'sudo -n systemctl stop rosy-io.service' | Out-Null
        $ioStopped = $true
        $probe = @(Invoke-RobotSsh 'sudo -n env PYTHONPATH=/opt/rosy/current/install/lib/python3.12/site-packages /opt/rosy/current/install/lib/bringup/dynamixel_probe --device /dev/rosy-motor --baudrate 1000000 --ids 1 2')
        if (($probe -join "`n") -notmatch 'PASS DXL id=1 responded with torque disabled' -or
            ($probe -join "`n") -notmatch 'PASS DXL id=2 responded with torque disabled') {
            throw 'Torque-free motor preflight did not pass for both IDs.'
        }
        [IO.File]::WriteAllLines((Join-Path $evidenceDir 'motor-preflight.txt'), $probe,
            [Text.UTF8Encoding]::new($false))
        $edit = @'
from pathlib import Path
import os, tempfile
p = Path('/etc/rosy/runtime.env')
old = p.read_text()
if old.count('ROSY_RUNTIME_MODE=core') != 1 or 'ROSY_IO_DRIVE_ENABLED=' in old:
    raise SystemExit('unexpected runtime settings')
if 'ROSY_DEVICE_UID=__UID__' not in old:
    raise SystemExit('device UID drift')
new = old.replace('ROSY_RUNTIME_MODE=core', 'ROSY_RUNTIME_MODE=motor').rstrip('\n') + '\nROSY_IO_DRIVE_ENABLED=true\n'
fd, name = tempfile.mkstemp(prefix='.runtime-motor-', dir=p.parent)
try:
    os.fchmod(fd, 0o640)
    with os.fdopen(fd, 'w') as out:
        out.write(new)
        out.flush()
        os.fsync(out.fileno())
    os.replace(name, p)
finally:
    if os.path.exists(name): os.unlink(name)
'@.Replace('__UID__', $uid)
        $changed = $true
        Invoke-RobotPython $edit
        Invoke-RobotSsh 'sudo -n systemctl restart rosy-core.service' | Out-Null
        Stop-CoreMotion
        Invoke-RobotSsh 'sudo -n systemctl start rosy-io.service' | Out-Null
        $ioStopped = $false
    }
    elseif ($info.runtime_mode -cne 'motor' -or
        $runtimeText -notmatch '(?m)^ROSY_IO_DRIVE_ENABLED=true$') {
        throw 'Device is not in a supported core or motor commissioning state.'
    }

    $ready = $false
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        $info = Get-Core '/api/v1/system/info'
        $capability = Get-Core '/api/v1/system/capabilities'
        $safety = Get-Core '/api/v1/safety/state'
        $robot = Get-Core '/api/v1/robot/state'
        if ($info.runtime_mode -ceq 'motor' -and $capability.teleop -and
            $capability.runtime.drive -ceq 'ready' -and $safety.estop -and
            $robot.evidence.pose.evidence -ceq 'fresh' -and
            $robot.evidence.velocity.evidence -ceq 'fresh' -and
            [math]::Abs([double]$robot.velocity.linear) -le 0.002) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Motor runtime did not become ready with fresh stationary odometry and E-Stop.' }
    $graph = Get-Core '/api/v1/system/runtime'
    $cmd = @($graph.ros.topics | Where-Object { $_.name -ceq ('/' + $info.ros_namespace + '/cmd_vel') })
    if ($cmd.Count -ne 1 -or [int]$cmd[0].publishers -ne 1 -or [int]$cmd[0].subscribers -ne 1) {
        throw 'Expected exactly one final cmd_vel publisher and one motor subscriber.'
    }
    $receipt = [pscustomobject]@{ device_name = $DeviceName; device_uid = $uid;
        robot_id = $info.robot_id; release_id = $complete.release_id; runtime_mode = 'motor';
        drive = 'ready'; estop = $true; cmd_vel_publishers = 1; evidence_dir = $evidenceDir;
        g4_approved = $false; completed_utc = (Get-Date).ToUniversalTime().ToString('o') }
    [IO.File]::WriteAllText((Join-Path $evidenceDir 'motor-readback.json'),
        ($receipt | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    $receipt | ConvertTo-Json -Compress
}
catch {
    $failure = $_
    try { Stop-CoreMotion } catch { }
    if ($changed) {
        try {
            Invoke-RobotSsh 'sudo -n systemctl stop rosy-io.service' | Out-Null
            $backup64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($runtimeText))
            $restore = @'
import base64, os, tempfile
from pathlib import Path
p = Path('/etc/rosy/runtime.env')
data = base64.b64decode('__BACKUP__')
fd, name = tempfile.mkstemp(prefix='.runtime-restore-', dir=p.parent)
try:
    os.fchmod(fd, 0o640)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.replace(name, p)
finally:
    if os.path.exists(name): os.unlink(name)
'@.Replace('__BACKUP__', $backup64)
            Invoke-RobotPython $restore
            Invoke-RobotSsh 'sudo -n systemctl restart rosy-core.service' | Out-Null
            Stop-CoreMotion
            Invoke-RobotSsh 'sudo -n systemctl start rosy-io.service' | Out-Null
            $ioStopped = $false
        }
        catch { Write-Warning ('Rollback needs operator attention: ' + $_.Exception.Message) }
    }
    elseif ($ioStopped) {
        try { Invoke-RobotSsh 'sudo -n systemctl start rosy-io.service' | Out-Null }
        catch { Write-Warning ('No-drive I/O restart needs attention: ' + $_.Exception.Message) }
    }
    throw $failure
}
