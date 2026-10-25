# Shared bounded SSH subprocess and timeout cleanup; callers own verification policy.
function Invoke-BoundedSshProcess {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][int]$TimeoutSec,
        [Parameter(Mandatory)][string]$ScratchDirectory
    )

    $executablePayload = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($Executable)
    )
    $argumentJson = ConvertTo-Json -Compress -InputObject @($Arguments)
    $argumentPayload = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($argumentJson)
    )
    $childScript = @"
`$executable = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$executablePayload'))
`$argumentJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$argumentPayload'))
`$childArguments = @(ConvertFrom-Json -InputObject `$argumentJson)
`$output = (& `$executable @childArguments 2>&1 | Out-String).Trim()
`$exitCode = `$LASTEXITCODE
if (`$output) { [Console]::Out.Write(`$output) }
if (`$null -eq `$exitCode) { exit 255 }
exit [int]`$exitCode
"@
    $encodedChild = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($childScript)
    )
    $hostExecutable = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    $stdoutPath = Join-Path $ScratchDirectory ".ssh-$([Guid]::NewGuid().ToString('N')).stdout"
    $stderrPath = Join-Path $ScratchDirectory ".ssh-$([Guid]::NewGuid().ToString('N')).stderr"
    $process = $null
    try {
        $process = Start-Process -FilePath $hostExecutable `
            -ArgumentList @("-NoProfile", "-NonInteractive", "-EncodedCommand", $encodedChild) `
            -PassThru `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        $null = $process.Handle
        if (-not $process.WaitForExit($TimeoutSec * 1000)) {
            if ($env:OS -eq "Windows_NT") {
                try {
                    & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
                    if ($LASTEXITCODE -ne 0 -and -not $process.HasExited) {
                        throw "Unable to stop the timed-out SSH process."
                    }
                }
                catch {
                    # Natural exit after the deadline still counts as timeout.
                    if (-not $process.HasExited) { throw }
                }
            }
            elseif (-not $process.HasExited) {
                $process.Kill()
            }
            $process.WaitForExit()
            return [pscustomobject]@{
                TimedOut = $true
                ExitCode = $null
                Output = ""
            }
        }
        $stdout = (Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue)
        $stderr = (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue)
        return [pscustomobject]@{
            TimedOut = $false
            ExitCode = $process.ExitCode
            Output = ($stdout | Out-String).Trim()
            Error = ($stderr | Out-String).Trim()
        }
    }
    finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}
