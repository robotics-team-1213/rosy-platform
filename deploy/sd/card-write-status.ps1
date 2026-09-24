[CmdletBinding()]
param(
    [string]$LogPath,
    [string]$ProgressPath,
    [switch]$Json,
    [double]$StallMinutes = 5,
    [string]$NowUtc
)
# Where is the card write, how fast, when does it finish, is it stuck? (D-188)
#
# Reads the D-187 progress file <log>.progress.jsonl that write-card.ps1 and
# prepare-rosy-sd.ps1 append to. Needs no elevation and never touches the card:
# write-card.ps1 creates the progress file as the operator before it elevates,
# and the elevated window only appends to it.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sd\card-write-status.ps1 -LogPath <log>
#   ... -Json            one JSON object for agents
#
# Release 005: nothing measured progress, and the operating agent gave several
# wrong completion times. The ETA here comes from the bytes the writer and the
# readback actually report, and from the pre-flight read rate for what is left.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$invariant = [Globalization.CultureInfo]::InvariantCulture
$utcStyle = [Globalization.DateTimeStyles]::AdjustToUniversal -bor [Globalization.DateTimeStyles]::AssumeUniversal

if (-not $ProgressPath) {
    if (-not $LogPath) { throw "-LogPath (or -ProgressPath) is required" }
    $ProgressPath = "$LogPath.progress.jsonl"
}
$suffix = ".progress.jsonl"
$exitMarker = $(if ($LogPath) { "$LogPath.exit" }
    elseif ($ProgressPath.EndsWith($suffix)) { $ProgressPath.Substring(0, $ProgressPath.Length - $suffix.Length) + ".exit" }
    else { "" })
$now = $(if ($NowUtc) { [DateTime]::Parse($NowUtc, $invariant, $utcStyle) } else { [DateTime]::UtcNow })
$stallLimit = [TimeSpan]::FromMinutes($StallMinutes)
$byteStages = @("write", "readback")

function ConvertTo-Utc([object]$Value) {
    if ($Value -is [DateTime]) { return $Value.ToUniversalTime() }
    return [DateTime]::Parse([string]$Value, $invariant, $utcStyle)
}

function Get-Field([object]$Line, [string]$Name) {
    if ($null -ne $Line -and $Line.PSObject.Properties[$Name]) { return $Line.$Name }
    return $null
}

function Get-NextByCardState([string]$CardState) {
    switch ($CardState) {
        "untouched" { return "re-run the same write-card.ps1 command" }
        "writing" { return "re-run the full write (without -ResumeAfterWrite)" }
        # D-230 3.2: the readback that -ResumeAfterWrite triggers is authoritative
        # (re-verifies every byte); say so, and name the fallback if it fails.
        "written-unverified" { return "re-run the same command with -ResumeAfterWrite; the readback re-verifies every byte, so a short card still fails there before the bundle or receipt are written; if the readback fails, re-run the full write (without -ResumeAfterWrite)" }
        "verified-no-bundle" { return "re-run the same command with -ResumeAfterWrite; the readback re-verifies every byte, so a short card still fails there before the bundle or receipt are written; if the readback fails, re-run the full write (without -ResumeAfterWrite)" }
        "bundle-partial" { return "re-run the full write (a partial bundle cannot be resumed)" }
        "complete" { return "check the registry for this device, then re-run the full write" }
        default { return "re-run the full write (without -ResumeAfterWrite)" }
    }
}

# --- read ---------------------------------------------------------------------
$text = $null
$readError = ""
if (-not (Test-Path -LiteralPath $ProgressPath -PathType Leaf)) {
    $readError = "no progress file at $ProgressPath yet: the write has not started, or the path is wrong"
}
else {
    try {
        # ReadWrite|Delete sharing: the writer appends while this reads.
        $stream = New-Object IO.FileStream($ProgressPath, [IO.FileMode]::Open, [IO.FileAccess]::Read,
            ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        try {
            $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8)
            $text = $reader.ReadToEnd()
        }
        finally {
            $stream.Dispose()
        }
    }
    catch {
        $inner = $_.Exception
        while ($inner.InnerException) { $inner = $inner.InnerException }
        if ($inner -is [UnauthorizedAccessException]) {
            $readError = "access denied reading $ProgressPath. An elevated window created it without your access; start writes with write-card.ps1, which creates the file as you first, or read it from an administrator console."
        }
        else {
            $readError = "cannot read ${ProgressPath}: $($inner.Message)"
        }
    }
}
if ($readError) {
    if ($Json) {
        [ordered]@{ progress_path = $ProgressPath; result = "unreadable"; error = $readError } | ConvertTo-Json -Compress
    }
    else {
        Write-Output "CANNOT READ PROGRESS: $readError"
    }
    exit 1
}

$lines = New-Object System.Collections.ArrayList
foreach ($raw in $text.Split("`n")) {
    if (-not $raw.Trim()) { continue }
    try { $line = $raw | ConvertFrom-Json } catch { continue }  # a line being written right now
    if (-not (Get-Field $line "ts") -or -not (Get-Field $line "stage")) { continue }
    $line | Add-Member -NotePropertyName utc -NotePropertyValue (ConvertTo-Utc $line.ts) -Force
    [void]$lines.Add($line)
}

$exitCode = $null
if ($exitMarker -and (Test-Path -LiteralPath $exitMarker -PathType Leaf)) {
    $exitCode = [int]((Get-Content -LiteralPath $exitMarker -Raw).Trim())
}

# --- interpret ----------------------------------------------------------------
$status = [ordered]@{
    progress_path = $ProgressPath
    stage = $null
    card_state = $null
    result = "not-started"
    detail = $null
    next = $null
    bytes_done = $null
    bytes_total = $null
    percent = $null
    rate_mbps = $null
    stage_eta_seconds = $null
    job_eta_seconds = $null
    stage_eta_utc = $null
    job_eta_utc = $null
    last_heartbeat_utc = $null
    last_heartbeat_age_seconds = $null
    stalled = $false
    stall_reason = $null
    waiting_for = $null
    stall_limit_seconds = [int]$stallLimit.TotalSeconds
    exit_code = $exitCode
    preflight = $null
}

if ($lines.Count -eq 0) {
    $status.detail = "no stage recorded yet: the write window has not started (approve the UAC prompt)"
    $status.next = "wait for the elevated window; if none appears, re-run write-card.ps1 -Detach and approve UAC"
    if ($null -ne $exitCode) {
        $status.result = "ended-without-result"
        $status.next = Get-NextByCardState "untouched"
    }
}
else {
    $last = $lines[$lines.Count - 1]
    $stageIndex = -1
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ((Get-Field $lines[$i] "detail") -notin @("heartbeat", "measured")) { $stageIndex = $i; break }
    }
    if ($stageIndex -lt 0) { $stageIndex = 0 }
    $stageLine = $lines[$stageIndex]
    $stage = [string]$stageLine.stage
    $status.stage = $stage
    $status.card_state = [string]$last.card_state
    $status.last_heartbeat_utc = $last.utc.ToString("o")
    $age = $now - $last.utc
    $status.last_heartbeat_age_seconds = [int][Math]::Max(0, $age.TotalSeconds)

    $preflight = $null
    foreach ($line in $lines) {
        if ($line.stage -eq "preflight" -and (Get-Field $line "detail") -eq "measured") { $preflight = $line }
    }
    if ($preflight) {
        $status.preflight = [ordered]@{
            read_mbps = Get-Field $preflight "read_mbps"
            raw_bytes = Get-Field $preflight "raw_bytes"
            assumed_write_mbps = Get-Field $preflight "assumed_write_mbps"
            assumed_readback_mbps = Get-Field $preflight "assumed_readback_mbps"
            predicted_total_seconds = Get-Field $preflight "predicted_total_seconds"
            min_read_mbps = Get-Field $preflight "min_read_mbps"
        }
    }

    # The stage that did the work, for a failure that came after it.
    $workStage = $stage
    $workIndex = $stageIndex
    if ($stage -eq "failed" -and $stageIndex -gt 0) {
        for ($i = $stageIndex - 1; $i -ge 0; $i--) {
            if ((Get-Field $lines[$i] "detail") -notin @("heartbeat", "measured")) { $workStage = [string]$lines[$i].stage; $workIndex = $i; break }
        }
    }

    $total = Get-Field $lines[$workIndex] "total"
    if ($null -eq $total -and $preflight) { $total = Get-Field $preflight "raw_bytes" }
    if ($null -ne $total -and [int64]$total -gt 0) { $status.bytes_total = [int64]$total }

    if ($workStage -in $byteStages) {
        # (time, bytes) from the stage start through its heartbeats.
        $points = New-Object System.Collections.ArrayList
        [void]$points.Add(@($lines[$workIndex].utc, [int64]0))
        for ($i = $workIndex + 1; $i -lt $lines.Count; $i++) {
            $line = $lines[$i]
            if ($line.stage -eq $workStage -and $null -ne (Get-Field $line "bytes")) {
                [void]$points.Add(@($line.utc, [int64]$line.bytes))
            }
        }
        $done = [int64]$points[$points.Count - 1][1]
        $status.bytes_done = $done
        if ($status.bytes_total) { $status.percent = [Math]::Round(100.0 * $done / $status.bytes_total, 1) }
        # Live rate over the last few heartbeats (up to 5 intervals).
        $first = $points[[Math]::Max(0, $points.Count - 6)]
        $lastPoint = $points[$points.Count - 1]
        $seconds = ($lastPoint[0] - $first[0]).TotalSeconds
        $gained = $lastPoint[1] - $first[1]
        if ($seconds -gt 0 -and $gained -gt 0) { $status.rate_mbps = [Math]::Round($gained / 1e6 / $seconds, 2) }
        # When the byte count last rose.
        $lastAdvance = $points[0][0]
        for ($i = 1; $i -lt $points.Count; $i++) {
            if ($points[$i][1] -gt $points[$i - 1][1]) { $lastAdvance = $points[$i][0] }
        }
    }

    if ($last.stage -eq "done") {
        $status.result = "complete"
        $status.next = $(if (Get-Field $last "next") { [string]$last.next } else { "the card is ready" })
    }
    elseif ($last.stage -eq "failed") {
        $status.result = "failed"
        $status.detail = [string](Get-Field $last "detail")
        $status.next = $(if (Get-Field $last "next") { [string]$last.next } else { Get-NextByCardState $status.card_state })
    }
    elseif ($null -ne $exitCode) {
        $status.result = "ended-without-result"
        $status.detail = "the write window ended (exit code $exitCode) without a final line"
        $status.next = Get-NextByCardState $status.card_state
    }
    else {
        $status.result = "in-progress"
        # ETA: the current stage from its live rate; what follows from the pre-flight.
        $readbackRate = $(if ($preflight -and (Get-Field $preflight "assumed_readback_mbps")) { [double]$preflight.assumed_readback_mbps } else { $null })
        $stageEta = $null
        if ($stage -in $byteStages -and $status.rate_mbps -and $status.bytes_total) {
            $stageEta = [Math]::Max([double]0, [double]($status.bytes_total - $status.bytes_done)) / 1e6 / $status.rate_mbps
        }
        $jobEta = $null
        if ($stage -eq "write" -and $null -ne $stageEta -and $readbackRate -and $status.bytes_total) {
            $jobEta = $stageEta + $status.bytes_total / 1e6 / $readbackRate
        }
        elseif ($stage -eq "readback") {
            $jobEta = $stageEta
        }
        elseif ($stage -in @("launch", "verify-signature", "select-disk", "preflight", "confirm") -and $preflight) {
            $jobEta = [double](Get-Field $preflight "predicted_total_seconds")
        }
        elseif ($stage -in @("bundle", "bundle-writing", "receipt")) {
            $jobEta = 0
        }
        if ($null -ne $stageEta) {
            $status.stage_eta_seconds = [int][Math]::Ceiling($stageEta)
            $status.stage_eta_utc = $now.AddSeconds($stageEta).ToString("o")
        }
        if ($null -ne $jobEta) {
            $status.job_eta_seconds = [int][Math]::Ceiling($jobEta)
            $status.job_eta_utc = $now.AddSeconds($jobEta).ToString("o")
        }

        # STALLED: bytes that stopped rising, or no line at all for the limit.
        if ($stage -in $byteStages) {
            $still = $now - $lastAdvance
            if ($still -gt $stallLimit) {
                $status.stalled = $true
                $status.stall_reason = "no new bytes in the $stage stage for {0:N0} min (limit {1:N0} min)" -f $still.TotalMinutes, $stallLimit.TotalMinutes
            }
        }
        elseif ($stage -eq "confirm" -or ($stage -eq "preflight" -and $preflight)) {
            $status.waiting_for = "the operator in the elevated window: the ERASE confirmation, or the answer to a slow-media warning"
        }
        elseif ($stage -eq "launch") {
            if ($age -gt $stallLimit) {
                $status.stalled = $true
                $status.stall_reason = "the elevated window has not started for {0:N0} min: the UAC prompt may be hidden behind other windows, declined or timed out" -f $age.TotalMinutes
            }
            else {
                $status.waiting_for = "the UAC prompt (approve it to start the write window)"
            }
        }
        elseif ($age -gt $stallLimit) {
            $status.stalled = $true
            $status.stall_reason = "no progress line for {0:N0} min in the $stage stage (limit {1:N0} min)" -f $age.TotalMinutes, $stallLimit.TotalMinutes
        }
        if ($status.stalled) {
            $status.next = "if the write window is gone or frozen, close it, then: " + (Get-NextByCardState $status.card_state)
        }
    }
}

# --- report -------------------------------------------------------------------
if ($Json) {
    $status | ConvertTo-Json -Depth 4 -Compress
    exit 0
}

function Format-Duration([object]$Seconds) {
    $minutes = [Math]::Ceiling([double]$Seconds / 60)
    if ($minutes -lt 1) { return "under 1 min" }
    if ($minutes -lt 60) { return "{0:N0} min" -f $minutes }
    return "{0}h {1:D2}m" -f [int][Math]::Floor($minutes / 60), [int]($minutes % 60)
}

function Format-Clock([string]$Utc) {
    return ([DateTime]::Parse($Utc, $invariant, $utcStyle)).ToLocalTime().ToString("HH:mm")
}

Write-Output "Card write progress: $ProgressPath"
if ($null -eq $status.stage) {
    Write-Output "Stage: none yet - $($status.detail)"
}
else {
    Write-Output "Stage: $($status.stage)   card_state: $($status.card_state)"
}
if ($null -ne $status.bytes_done) {
    $totalText = $(if ($status.bytes_total) { "{0:N0} MB ({1:N1} %)" -f ($status.bytes_total / 1e6), $status.percent } else { "unknown total" })
    Write-Output ("Bytes: {0:N0} MB of {1}" -f ($status.bytes_done / 1e6), $totalText)
}
if ($status.rate_mbps) { Write-Output ("Rate: {0:N1} MB/s over the last heartbeats" -f $status.rate_mbps) }
if ($status.preflight -and $null -ne $status.preflight.read_mbps) {
    Write-Output ("Pre-flight read: {0:N1} MB/s (slow-media limit {1:N1} MB/s)" -f $status.preflight.read_mbps, $status.preflight.min_read_mbps)
}
if ($null -ne $status.stage_eta_seconds) {
    Write-Output ("ETA this stage: {0} (about {1})" -f (Format-Duration $status.stage_eta_seconds), (Format-Clock $status.stage_eta_utc))
}
if ($null -ne $status.job_eta_seconds) {
    Write-Output ("ETA whole job: {0} (about {1})" -f (Format-Duration $status.job_eta_seconds), (Format-Clock $status.job_eta_utc))
}
if ($null -ne $status.last_heartbeat_age_seconds) {
    Write-Output ("Last progress line: {0} s ago" -f $status.last_heartbeat_age_seconds)
}
if ($status.waiting_for) { Write-Output "Waiting for: $($status.waiting_for)" }
if ($status.stalled) { Write-Output "STALLED: $($status.stall_reason)" }
switch ($status.result) {
    "complete" { Write-Output "Result: COMPLETE" }
    "failed" { Write-Output "Result: FAILED - $($status.detail)" }
    "ended-without-result" { Write-Output "Result: ENDED WITHOUT RESULT - $($status.detail)" }
}
if ($null -ne $status.exit_code) { Write-Output "Exit code: $($status.exit_code)" }
if ($status.next) { Write-Output "next: $($status.next)" }
exit 0
