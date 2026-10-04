# D-443 Q8 charging safety tag — 2026-10-04

Candidate `fix/d443-charge`, parent `f17f4f906`; tag and regression committed with this evidence. Added `middleware/core/services/core_features/docking/charging.py` to `safety_modules` and its `ChargingConfirmation` non-public safety anchor. D-27 discharge-stop suppression input now receives D-430 review/trailer controls; runtime behavior is unchanged.

Missing tag reproduced: 1 failed. After tag and required anchor: `python -m pytest test/architecture/test_safety_separation.py test/test_safety_review.py -q`: **12 passed**, 61.27 s. Raw logs `X:/DevTemp/rosy-d427/resume/charge-red.txt`, `charge-green-2.txt`. Independent reviewer `/root/d427_safety_review`: no source blocker, conditional on structural/trailer tests; that local test condition passed. Candidate commit trailer is additionally checked after commit.

SOURCE/local static proof only; CI, ARM64, charging hardware and FIELD acceptance NOT_RUN. No charging output or voltage threshold changed.
