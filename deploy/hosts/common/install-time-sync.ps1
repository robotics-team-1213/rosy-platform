# D-859: run in an elevated maintenance shell; -WhatIf previews without changing W32Time.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')]
    [string]$Server,
    [switch]$Maintenance
)

$ErrorActionPreference = 'Stop'
if (-not $Maintenance) { throw 'Use -Maintenance after stopping all workloads; resync can step the clock.' }
if ((Get-CimInstance Win32_ComputerSystem).PartOfDomain) {
    throw 'Domain-joined host: configure the domain time hierarchy with its administrator.'
}
if (Test-Path 'HKLM:\SOFTWARE\Policies\Microsoft\W32Time') {
    throw 'W32Time is policy-managed; configure the policy with its administrator.'
}
if ($PSCmdlet.ShouldProcess('Windows Time service', 'Use the approved site NTP server and resync')) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run from an elevated PowerShell maintenance shell.'
    }
    $backup = Join-Path $env:TEMP ('rosy-w32time-' + [guid]::NewGuid().ToString() + '.reg')
    & reg.exe export 'HKLM\SYSTEM\CurrentControlSet\Services\W32Time' $backup /y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not back up W32Time; no settings changed.' }
    Write-Host "W32Time registry backup: $backup"
    $timeConfig = 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Config'
    Set-ItemProperty -LiteralPath $timeConfig -Name MinPollInterval -Value 6
    Set-ItemProperty -LiteralPath $timeConfig -Name MaxPollInterval -Value 6
    Set-Service W32Time -StartupType Automatic
    # Automatic startup alone does not keep W32Time running on a workgroup PC (Microsoft KB 2385818).
    & sc.exe triggerinfo W32Time start/networkon stop/networkoff
    if ($LASTEXITCODE -ne 0) { throw "Could not set W32Time network triggers. Backup: $backup" }
    Start-Service W32Time
    & w32tm.exe /config "/manualpeerlist:$Server,0x8" /syncfromflags:manual /update
    if ($LASTEXITCODE -ne 0) { throw "W32Time configuration failed. Backup: $backup" }
    & w32tm.exe /resync /rediscover
    if ($LASTEXITCODE -ne 0) { throw 'W32Time resync failed; configured but synchronization is unverified.' }
    & w32tm.exe /query /status /verbose
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify W32Time status.' }
    & w32tm.exe /query /peers
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify W32Time peers.' }
    Write-Host 'Inspect source, last successful sync and offset. This output does not certify the Linux 50 ms bound.'
}
