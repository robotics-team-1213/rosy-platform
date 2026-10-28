# Passive OMX articulation diagnostic

The contact diagnostic now preserves all seven publisher-supplied joint positions
and rejects stale or damaged evidence before homing and policy launch.
The policy model, command owner, admission, six-joint controller feedback,
tolerances, world collision geometry and physics parameters are unchanged.
The existing independent policy evaluation remains HOLD.

## Committed source and remote checks

Source commit `b2421f9f7bab712278d4fa847fe130e38455b7c7` contains the collector,
observer/job integration and tests. RED commit `57ec5935f3` failed26 remote tests:
the articulation module/readiness/final-artifact integration did not exist.
Production commit `c7e10f5ae1` passed50 tests with one SDK skip; the source commit
then passed52 tests with one SDK skip after adding zero-time warmup and the
post-homing launch-refusal integration test. The final source additionally
preserves first/latest source stamps even when the last message is throttled:
53PASS, one SDK skip, NEW0. Prior artifacts remain in their original directories.

The collector validates every message before storage throttling. It preserves
publisher order, all seven positions, optional velocities, frame/source stamps
and monotonic receipts. Duplicate/missing/extra joints, nonfinite values,
shape/clock errors and storage truncation make capture incomplete. Positive
advancing stored samples establish readiness; only source-stamp advances refresh
its progress receipt. Startup time zero is allowed before positive samples.
Atomic status is refreshed at most every100ms. Both launch boundaries require
clean status with progress age in[0,500ms]. Missing/stale evidence prevents
launch. Invalidity after launch still fails final evidence verification.

The observer remains a separate receive-only process. No action publisher or
owner callback was added. It shuts down before verifying/hash-binding the two
artifacts, followed by unconditional global child cleanup. The job integration
test explicitly loses the stream during homing and proves no policy process
starts. Independent architecture and critic review of the source commit found
no Important findings.

## Actual isolated SDK transport

AI-PC native SDK run at the source commit:1PASS,0SKIP, terminal EXIT0,2.64seconds
pytest time. The runner selected4CPU/4GiB with a5-minute total limit; its startup
output and preserved wrapper record that selection. No separate live-scope
resource-property snapshot was collected for this transport probe. The existing
two-contact world contains no robot. A separately owned synthetic publisher on
`/articulation_probe/joint_states` verifies namespace-derived subscription,
seven positions, original timestamps/frame, empty optional velocity, capture
closure and child cleanup. Its source is `synthetic_transport_only`; the closure
explicitly records `actual_robot_articulation_verified=false`. There were zero
robot models, robot commands, policy inferences and optimizer steps.

The captured trace contains93 received messages and93 stored samples,
invalid0/truncatedfalse. Source stamps span1792831657819855364 through
1792831659659407545ns. Maximum observed receipt gap21169316ns; end gap21362112ns.
These are transport observations, not timing acceptance for actual robot poses.

External evidence root: `C:/DevTemp/learning-execution-20261023/`.

| Artifact | SHA-256 |
|---|---|
| articulation-transport-sdk-final/out/pytest-tmp/**/policy-articulation.json | `8911ceb94ff3c49b38c749a24e05e0669f347ae34fd23b256ebd8b912b61e024` |
| articulation-transport-sdk-final/out/pytest-tmp/**/policy-contacts.json | `4c108ad4d17bcb4653599430d9ef468407f6c5b85d39c296c17a794dd06bf876` |
| articulation-transport-sdk-final/out/pytest-tmp/**/contact-probe-closure.json | `1538dbb5b3c5f121dd6d64b07df296cd4b1b7c220280e7e8d34827e0039b19c9` |

Commands: ordinary runner `python tools/remote/remote_pytest.py --log-dir <external>/articulation-final-stamps -- test/test_omx_sim_policy_articulation.py test/test_omx_sim_policy_contacts.py test/test_omx_sim_contacts_ros.py -q`;
separate SDK wrapper `<external>/run_articulation_transport_final.py --sha b2421f9f7b`.
SDK uses the official remote_sim runner with AI placement and source-HEAD check.
Wrapper SHA256 is `8a501bd10a9f53d30d17f11fb6dde836b2cd752c3584fe192b76018530f5df49`.
Logs are `articulation-red/run-1.txt`, `articulation-final-stamps/run-1.txt` and
`articulation-transport-sdk-final/run.txt`. General-run SDK skips are not counted as
actual SDK execution. There is no physical-device acceptance or real HF transfer.

## Next acceptance

After official landing, freeze exact source/dependency/model inputs for at most
one calibration and one contact-articulation policy episode under the existing
4CPU/4GiB/600second budget. Preserve producer package/hash correspondence,
joint2 startup and real seven-name trace. Event geometry additionally needs
shared-clock/frame evidence and two-sided articulation brackets within50ms.
Unsupported events remain unknown. A captured trace never upgrades policy HOLD.
Formal trials remain0; no new learned-policy episode was run for this change.

CE: 미해결 — observation coverage improved, but the physical cause of the
independent policy failure has not been resolved. No solved-problem lesson added.
