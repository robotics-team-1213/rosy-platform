---
title: Diagnose GPT capacity relocation before replacing a card after readback failure
date: 2026-10-28
category: workflow-issues
module: deploy/robot/pinky_pro/sd
problem_type: integration_issue
component: development_workflow
severity: high
symptoms:
  - "The complete image write succeeded but readback stopped at byte offset 528."
  - "Restoring the signed primary header once succeeded, but ordinary resume failed at the same offset."
root_cause: missing_workflow_step
resolution_type: code_fix
tags: [sd-writer, gpt, windows, readback, fail-closed, media-evidence]
applies_when:
  - "A signed GPT image is smaller than its physical SD card and storage discovery changes its capacity fields."
---

# Diagnose GPT capacity relocation before replacing the card

## Problem and verified cause

The first A/B engineering card completed its raw image write, then failed at
offset 528, the primary GPT header CRC. The generic failure recommendation was
a full rewrite and eventual card replacement. A repeated write was not supported
by the observed evidence.

An elevated, read-only capture found only eight differing bytes in the first
128KiB. The primary header's backup LBA and last usable LBA described the physical
card capacity instead of the smaller signed image, with a matching recalculated
CRC. The disk GUID and partition entries were unchanged. The original image-end
backup and a physical-card-end backup both had valid header and table CRCs.
This established capacity relocation; the exact component that performed the
relocation was not isolated.

One signed-sector restoration passed immediate readback, then failed again after
the normal storage-discovery lifecycle. Restoring only once before the standard
entry point was insufficient. Discovery and provisioning mounts occur at more
than one point in the workflow.

## Recovery and prevention

Pending commit: `02d0dd9817fed6407c88b916c1f3de0377a4517f`.
This change was tested on the actual card but is not yet a claim of main landing
or public publication.

The shared restore helper authenticates the compressed image and original GPT,
then accepts either the exact original header or exactly the observed capacity
fields plus their dependent CRC. Other header, table, MBR or original-backup
changes fail before any write. At most the signed primary sector is restored;
the ordinary full readback is retained.

The device handle must be pinned before the lengthy image-authentication pass.
Reopening a physical disk number afterward would permit number reuse during that
pass. Fresh USB identity and fingerprint checks still precede handle selection.

Restoration runs after the final pre-readback discovery, after provisioning mount
selection, and after configuration copying. The last restore and raw layout check
precede completion; no subsequent storage-discovery call is made by that path.
Ordinary `-ResumeAfterWrite` supports this recovery. The restriction on earlier
failed attempts belongs to emergency resume, not ordinary verified resume.

For a matching prior attempt, keep the reviewed plan and run the standard entry
point with `-ResumeAfterWrite`; do not manufacture receipts or use emergency mode.
If the strict helper rejects a different change, preserve raw evidence and stop.
Do not broaden allowed drift or assume the same cause.

## Verification and limits

The approved remote SD-tools cohort passed 94 cases without skips. Independent
review caught and verified the device-handle timing correction. Actual standard
resume then read all 31,138,512,896 image-prefix bytes, provisioned the card,
registered its identity and exited zero after the final GPT check. Its receipt
records `fixture: false`, `resumed_after_write: true`, and verified media.

The existing FAT comparison policy permits specified Windows metadata and system
index files. Consequently the receipt's whole-prefix raw digests can differ even
when verification passes; consult its boot-partition comparison results instead
of treating equal raw digests as the only valid result. The GPT exception was
not added to that comparison policy.

Operator evidence is retained outside Git under the workspace's
Rosy/artifacts/receipts/2026-10-27-full-os-integration directory: the bounded
gpt-readonly-01 capture, the failed one-sector recovery attempt, and the successful
resume-gpt-fixed log and receipt. No device serial, address or private key is
included in this learning.

Three authenticated full-image passes add processing time. Measure that cost
before optimizing it; an authenticated metadata snapshot could avoid repeated
decoding, but an unauthenticated cache would change the trust boundary.
MEDIA acceptance here does not establish first boot, physical OTA or rollback.
