# D-442 U2 Task 1 publisher identity gate — 2026-10-04

Candidate: `feat/d442-port`, parent `89bcfd1f7`. This first task adds static regression only; the contracts/motion package, runtime PinkyTwistPort and artifact delivery remain pending. Plan: docs/plans/2026-10-04-d442-pinky-port.md.

The gate follows publishers of cmd_vel or /cmd_vel from topic literals, module constants and declared parameter defaults through alternate attributes and local aliases. It scans the existing D-430 tracked production scope (>500 Python files), retains the enumerated Gazebo bench exclusion, and permits the D-208 legacy node only for the exact None-if-sensor_only creation guard. Inverse and other-condition branches remain violations. Runtime remaps, dynamically built topics and unbounded interprocedural aliasing remain review-only; this is static evidence, not DDS enforcement.

- Initial helper absent: 9 RED tests. Independent review reproduced inverse conditional omission; inverse guard and local parameter-variable regressions were both RED, then fixed by checking both nonexempt branches and tracking the topic variable.
- An actual RosBridge source mutation added unsafe_other with `_pub = create_publisher(Twist, "cmd_vel", ...)` and `_pub.publish`. The production gate rejected the extra writer; the original source bytes were restored in finally and source status is clean. Log: `X:/DevTemp/rosy-d427/resume/port-ast-live-mutation.txt`.
- New gate plus existing safety separation: **18 passed**, 40.16 s; known_failures **0 new**. Log: `X:/DevTemp/rosy-d427/resume/port-ast-final.txt`. One existing SyntaxWarning came from parsing the new-device setup source.
- Independent reviewer `/root/d427_safety_review`: **APPROVE Task 1**, independently **11 passed**, 33.70 s and four hostile fixtures detected. Wrapper/contracts/artifacts are outside this approval.

SOURCE/local static proof only. CI, ROS-SIM, ARM64, actual final publication, DEVICE and FIELD are NOT_RUN for this task. No operating writer, topic, publisher location or bridge arguments changed.
