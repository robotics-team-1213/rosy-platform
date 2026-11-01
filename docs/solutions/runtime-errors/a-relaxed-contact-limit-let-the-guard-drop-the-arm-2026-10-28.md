---
title: Raising the soft-contact limit toward the guard bound let a descent press until the guard dropped the arm
date: 2026-10-28
category: runtime-errors
module: deploy/robot/omx (chunk_runner.py soft contact, guarded_native.py guard)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "contact in descend_pick: a joint lagged the command by 2.3 units"
  - "session ended: ValueError: wrist_flex: following error >5 motor degrees; command=3061, current=3118"
  - "torque OFF with the arm extended over the Pinky; it came to rest on the Pinky body"
root_cause: wrong_assumption
resolution_type: revert
severity: critical
tags: [omx, arm-s, guard, soft-contact, safety, threshold]
applies_when: "changing runner.contact_lag or any limit that decides when a descent stops pressing"
---

# A contact limit near the guard bound is not a safe contact limit

**Why we changed it.** While holding a box, the elbow reached the hover with a steady 1.5–2.0 unit lag. With an empty gripper it was 0.6–0.8; the cause is P-only control under load. Every place descent was therefore called a contact within 1 cm. To fix that, the limit became "start lag + 1.5, capped at 2.5". The cap was chosen because the guard trips at about 2.8 units (5°).

**What happened.** The very next empty pick descended onto a box edge on the Pinky tray. That pick used a bias borrowed from the floor.

- Contact was declared only at 2.3 units.
- The arm had pressed longer, so the retreat (back up the same path) pushed wrist_flex past the guard's 5°.
- The session ended and torque went off with the arm extended, and it came to rest on the Pinky.

**The mistake.** The cap was compared with the guard bound as a static number. The retreat that follows a contact moves the joint again, so the following error at retreat is larger than at detection. A late detection leaves no room for it.

**Fix.** Reverted to the absolute 1.5 unit limit (commit `bf200ec77a`). The field runner copy with the relaxed limit was retired.

**Rules for next time:**
- Keep the soft-contact limit far below the guard bound, about half of it. Never relax the limit to make a load case pass.
- Solve the held-box start lag another way. Options: wait for the lag to settle before a contact chunk, measure the load lag per pose, or approach slower.
- Whatever the fix, it must keep empty descents stopping at the old limit.
- Any change to a stop threshold gets a test of the unloaded case it must not weaken (`test_omx_chunk_runner.py`), not only the loaded case it fixes.

**Replacement (tested, not yet run on the arm).** Contact limits are now per joint (`chunk_runner.contact_limits`, `runner.contact_rise`, `runner.contact_loaded_max`).

- A joint that starts a contact chunk with little lag keeps exactly 1.5.
- Only a joint already loaded at the start (the held-box elbow) gets start + 0.6, at most 2.2.
- The test pins the unloaded case to 1.5 on every joint.
- Before any real place uses it, check it first with an empty descent over plain floor (field copy `omx-tools-smoothpace7`).

**Recovery used.** A person folded the arm by hand with torque off.
