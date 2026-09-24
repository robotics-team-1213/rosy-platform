---
title: An interrupted write zeroes sector 0, and Get-Disk reports that as a different card's identity every time
date: 2026-09-24
category: workflow-issues
module: deploy/sd (prepare-rosy-sd.ps1, Pinky Pro release 2026.09.24-010)
problem_type: logic_error
component: development_workflow
symptoms:
  - "a fresh -PlanOnly plan for the same physical card was refused as \"a different card\" after an interrupted Imager write"
  - "Get-Disk reported PartitionStyle MBR, Signature 1 even after a reseat"
  - "a raw sector-0 probe (requires the 0x55AA boot signature) reported no signature for the same disk"
  - "two prior guesses at the cause were wrong before sector 0 was dumped"
root_cause: missing_validation
resolution_type: code_fix
severity: high
related_components: [tooling]
tags: [sd-writer, disk-identity, mbr-signature, windows, get-disk, fail-closed, pinky-pro]
---

# An interrupted write zeroes sector 0, and Get-Disk reports that as a different card's identity every time

## Problem

An Imager write interrupted earlier in the same release-010 session left the card's first sector
all zero. `prepare-rosy-sd.ps1 -PlanOnly` uses the disk's MBR signature (from `Get-Disk`) and GUID
as part of the card identity it records in the plan, then refuses to erase a card whose identity
does not match the plan. With an all-zero sector 0, `Get-Disk` reports `PartitionStyle MBR`,
`Signature 00000001` — the same value it reports for every other all-zero card, including after a
reseat — while a raw probe of the sector (which only recognizes a signature when the sector ends in
the `0x55AA` boot marker) reports no signature at all for the same disk. The two readers disagreed,
and every fresh plan against the same physical card was refused as belonging to a different card.

## Symptoms

- `prepare-rosy-sd.ps1 -PlanOnly` on the intended card produced a plan whose identity never matched
  a previous plan for that same card, across repeated attempts and a reader reseat.
- `Get-Disk` consistently showed `Signature 00000001` and no GUID.
- A raw sector-0 dump (elevated, read-only) showed all zero bytes, not a real MBR.

## What Didn't Work

- Trusting `Get-Disk`'s signature alone as card identity. `Signature 1` is not a real signature on
  an all-zero card — it is what `Get-Disk` falls back to reporting — so it collides with any other
  blank card `Get-Disk` describes the same way.
- Two earlier hypotheses (guessed before the sector was actually read) about what was different
  about the card. Diagnosis only converged once sector 0 was dumped and compared byte-for-byte
  against what `Get-Disk` claimed.

## Solution

`prepare-rosy-sd.ps1` now records `disk_partitions` in the plan alongside the disk signature and
GUID, and treats an all-zero, no-partition, signature-`1` disk as the identity-less "factory blank"
case rather than as a mismatch:

```powershell
# 2026-09-24: Get-Disk reports an all-zero first sector (e.g. after an
# interrupted Imager write) as MBR signature 1, and -PlanOnly records that.
# Such a card has no identity of its own: it is the factory-blank case below.
if (-not $found.Signature -and $planned.Signature -ceq "00000001" -and -not $planned.Guid -and
        $planKeys -ccontains "disk_partitions" -and $null -ne $reviewedPlan.disk_partitions -and
        [int]$reviewedPlan.disk_partitions -eq 0 -and
        $Sector.PSObject.Properties["Blank"] -and $Sector.Blank) {
    $planned.Signature = $null
}
```

A disk whose signature happens to be a *real* `1` (a genuine MBR, not an all-zero sector) still
refuses to match, because `disk_partitions` and the sector's `Blank` flag distinguish the two cases
that `Get-Disk`'s signature field alone cannot. And when the sector cannot be read right before the
erase, the script fails closed instead of trusting the disk-signature-only identity (PR #37 review):

```powershell
elseif ($Sector -and -not $Sector.Read -and $found.Signature -ceq "00000001" -and -not $found.Guid) {
    # Get-Disk reports every all-zero card as signature 1, so without the
    # sector this identity proves nothing (PR #37 review).
    Fail "the card's first sector could not be read right before the erase; its identity cannot be confirmed" "reseat the card reader, then re-run"
}
```

## Why This Works

`disk_partitions` and a direct sector-0 read give a second, independent signal that `Get-Disk`'s
signature field cannot fake: an all-zero sector cannot also report a nonzero partition count, so the
factory-blank case and a genuine signature-1 card are distinguishable even though `Get-Disk` reports
them identically. Requiring a successful sector read before trusting a signature-1 identity closes
the remaining gap — an *unread* sector proves nothing either way, so the script refuses rather than
guesses.

## Prevention

- When two identity readers disagree (here: `Get-Disk`'s cached view vs. a raw sector probe), read
  the underlying bytes before forming a theory. Two guesses were made and discarded before the
  sector dump settled it.
- A hardware identifier reported the same way for two different underlying states (a real signature
  vs. "no signature, reported as a default") needs a second, independent signal before it is trusted
  for a destructive-action gate.

## Related Issues

- [windows-quickedit-freezes-elevated-console-writes-2026-09-24.md](windows-quickedit-freezes-elevated-console-writes-2026-09-24.md)
- [long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md](long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md)
