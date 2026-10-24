# Passive OMX articulation diagnostic

The contact diagnostic now preserves all seven publisher-supplied joint positions
and rejects stale or damaged evidence before homing and policy launch.
The policy model, command owner, admission, six-joint controller feedback,
tolerances, world collision geometry and physics parameters are unchanged.
The existing independent policy evaluation remains HOLD.

## Committed source and remote checks

Source commit `afd400b7bc8ae856b813a11048cf068b332f4271` contains the collector,
observer/job integration and tests. RED commit `57ec5935f3` failed26 remote tests:
the articulation module/readiness/final-artifact integration did not exist.
Production commit `c7e10f5ae1` passed50 tests with one SDK skip; the source commit
then passed52 tests with one SDK skip after adding zero-time warmup and the
post-homing launch-refusal integration test. Known-failure comparison: NEW0.

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

AI-PC native SDK run at the source commit:1PASS,0SKIP, terminal EXIT0,2.89seconds
pytest time. The runner applied4CPU/4GiB with a5-minute total limit. The existing
two-contact world contains no robot. A separately owned synthetic publisher on
`/articulation_probe/joint_states` verifies namespace-derived subscription,
seven positions, original timestamps/frame, empty optional velocity, capture
closure and child cleanup. Its source is `synthetic_transport_only`; the closure
explicitly records `actual_robot_articulation_verified=false`. There were zero
robot models, robot commands, policy inferences and optimizer steps.

The captured trace contains100 received messages and85 stored samples,
invalid0/truncatedfalse. Source stamps span1792830243548157406 through
1792830245628261091ns. Maximum observed receipt gap123894889ns; end gap9613182ns.
These are transport observations, not timing acceptance for actual robot poses.

External evidence root: `C:/DevTemp/learning-execution-20261023/`.

| Artifact | SHA256 |
|---|---|
| articulation-transport-sdk/out/pytest-tmp/**/policy-articulation.json | `529eab0d951085d22dd6fc7d830a3a3a90524ff1f3b33e69afeba9ffb54fc32e` |
| articulation-transport-sdk/out/pytest-tmp/**/policy-contacts.json | `a25163caa5c5023dfe974806a2d021fdeb3449b0e6f339754f3670c672952f3f` |
| articulation-transport-sdk/out/pytest-tmp/**/contact-probe-closure.json | `28f8ff797ec288264d725a6131f757d197542beb062bb8d97d7e819c1d55ddd0` |

Commands: ordinary runner `python tools/remote/remote_pytest.py --log-dir <external>/articulation-green-final -- test/test_omx_sim_policy_articulation.py test/test_omx_sim_policy_contacts.py test/test_omx_sim_contacts_ros.py -q`;
separate SDK wrapper `<external>/run_articulation_transport.py --sha afd400b7bc`.
SDK uses the official remote_sim runner with AI placement and source-HEAD check.
Logs are `articulation-red/run-1.txt`, `articulation-green-final/run-1.txt` and
`articulation-transport-sdk/run.txt`. General-run SDK skips are not counted as
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
