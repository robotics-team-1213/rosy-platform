# Proposer lookup after a lost recovery request reply — 2026-10-28

Follow-up to [public recovery source verification](../transfer-recovery-public-2026-10-27/result.md). The earlier record remains frozen. This is simulation source/browser evidence; local landing is still a separate gate, and no push, device operation, producer installation or VLA training is claimed.

## Trigger and fix

The original service proposer must be able to query the job after a lost recovery-request reply. The expanded real HTTP/browser test aborts that reply only after the server commits it, explicitly requeries, checks exactly one proposer POST, and continues through independent observations and a different operator's approval. It also retains the separate lost approval reply, child GET503, same-child budget and synthetic completion assertions.

Source commit `38bc992ab0` produced one focused RED. The requery click itself succeeded, but the mission-ID query input remained disabled by the generic operator-only control selector. The failure was `unexpected value disabled` on the lookup textbox; this record does not mislabel it as a failed HTTP request or an unperformed backend commit.

Source commit `ce1ef8ebb02e4709d4636d0abb912f6fb57d7527` marks the existing GET lookup button with `data-work-read` and excludes exactly the mission-ID query input from operator-only inputs. Backend authentication, ownership, request eligibility, approval identity, confirmation/lifetime and execution controls are unchanged. Editing the lookup continues to invalidate the displayed job and any pending approval eligibility.

## Actual verification

```powershell
python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-recovery-proposer-read-green" -- ROSY_RUN_BROWSER_TESTS=1 operations/fleet/test/test_transfer_recovery_console_browser.py operations/fleet/test/test_arm_transfer_console_browser.py -s
python test/known_failures.py "$env:TEMP/rosy-recovery-proposer-read-green/run-1.txt"
```

Result on source commit `ce1ef8ebb0`: **14 passed, zero skipped**, runner/classifier exit0, NEW0/known0/flaky0. Node syntax and the existing admission unit passed. The source selection used the approved remote test workflow, not a local product browser.

Independent contract reread of b45e8d3a92..ce1ef8ebb0 found no supported regression: exemptions cover only GET lookup controls and command authority remains guarded. It did not rerun tests or certify a device.

The six actual remote final-state PNGs were fetched byte-for-byte to the external system-TEMP folder rosy-recovery-public-screenshots/ce1ef8ebb0 and checked against the committed test's printed SHA-256. The final 320/390 captures match the earlier reviewed final-state pixels; 1920 was opened again and preserves the same composition. These are final confirmed-child captures after the loss branches have been resolved, not intermediate error-state screenshots.

| Captured case | Integrity |
|---|---|
| 320px normal / lost branch | SHA-256 `bdb15cc2076ef0d27b0a67402859186bb304459e88d22b709a0040799770d004` |
| 390px normal / lost branch | SHA-256 `2f401b83bd83e89a63d61cd8e43274d7e58ee8ccf867f02916f1e922cdd3e9bb` |
| 1920px normal | SHA-256 `26639168e6d886b8101024b8f994b24caaa13f7f3299156d82d60fa68df2c2cc` |
| 1920px lost branch | SHA-256 `1d547aefea636a009e3d744d253d4dd4da22af0328b034a32b55d2c931181829` |

The waiting public launcher was deliberately stopped before it began native landing so this caller fix could be committed and tested. The contract's native verification continued on its own tree. Resume the official public landing only after the shared contract is on local main and the public tree is committed/clean; do not substitute these focused tests for its current native gate.

CE: no additional lesson for this lookup adjustment; its cause and behavior are explicit in the selector and regression. The previous clipping lesson remains the new durable learning for this work. No DESIGN, CONCEPTS, instruction, asset or dependency changes were needed.
