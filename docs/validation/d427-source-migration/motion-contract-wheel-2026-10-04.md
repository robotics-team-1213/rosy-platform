# D-442 §4(a) ROS-free motion contracts — 2026-10-04

Candidate: feat/d442-port, parent da67f678a. Scope is type representation only; runtime port binding and native/SD/core Docker delivery remain Task 3. Constructing a MotionIntent, FLEET priority or POLICY envelope reference grants no execution authority.

Added namespace wheel rosy-contracts-motion==0.1.0 with exact rosy-contracts-skill==0.1.0 dependency and COLCON_IGNORE. The manifest assigns it to contracts; CI builds and installs both actual wheels. The 27 ROS package inventory is unchanged.

Six semantic kinds carry immutable SI payloads and common identity/monotonic validity. Nested maps/vectors are independently frozen. Existing AttemptIdentity is reused with device/workcell agreement. OMX TrajectoryCommand preserves all fields, including trajectory points, optional joint names, phase, expected start state and tolerances; its 1e-9 final-time tolerance is retained. Capabilities declare servo kinds, strict stream/goals flags, immutable semantic limits; physical E-stop remains unknown unless supplied. The Protocol exposes no rearm or stop release.

Evidence:
- Initial absent contracts and hostile scalar/identity/immutability cases were RED before implementation. Independent review caught omitted FLEET/IDLE representation: both regressions RED then fixed. Future OMX/POLICY producer cases are representation tests only.
- Fresh v2 wheels built from source copies exclusively under X:/DevTemp/rosy-d427/resume/motion-wheel-source-v2, installed together under motion-wheel-site-v2. No source PYTHONPATH was used: **52 passed**, 0.22 s. Logs: motion-wheel-build-v2.txt, motion-wheel-install-v2.txt, motion-wheel-test-v2.txt in that X resume directory.
- Installed wheel plus relevant manifest/dependency/colcon/module/safety architecture: **121 passed**, 38.20 s; log motion-contract-architecture.txt.
- Independent reviewer /root/d427_safety_review: **APPROVE Task 2**, installed-v2 **52 passed**, 0.10 s. Both imports came from the X installation; installed source matched final source, metadata dependency and namespace coexistence passed. No ROS/backend import or production motion-contract consumer exists.

SOURCE/host/wheel evidence only. Binding authority/admission, native/SD/core Docker delivery, CI, ROS-SIM, ARM64, DEVICE and FIELD are pending. U2 is not complete.
