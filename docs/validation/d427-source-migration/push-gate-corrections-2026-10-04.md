# D-427 enforced push gate corrections — 2026-10-04

Candidate: `fix/d427-resume`, parent `64415a609`. The enforced push rejected this tree: main affected invocation **7 failed, 12,304 passed, 499 skipped, 1 collection error**, 6,043.47 s; perception-related second invocation **2,836 passed, 112 skipped**, 495.18 s; face lint tests **3 skipped**. Log: `X:/DevTemp/rosy-d427/resume/push-2.txt`. This rejected push is not a green gate or remote-main result.

Corrected generated training notebook path drift; IR launch exclusivity now scans manifest colcon roots rather than empty legacy src; Docker source/whitelist assertions preserve deliberate `/opt/rosy_ws/src` container destinations; description mesh bootstrap uses the actual COPY destination; live learned-perception/IR deployment docs name current source paths and runbook checks cover all current roots. The ROS-only map monitor explicitly requires rclpy and is NOT_RUN on Windows. The verify-inputs.sh syntax failure was a Windows WSLService connection error 0x8007274c, with no script diagnostic; genuine Git Bash syntax check exits 0.

Related Windows host suites **124 passed, 1 skipped**, 26.32 s; known_failures **0 new, 0 known**. After mesh path correction the runtime contract **34 passed**, 1.40 s. Working Git Bash is first on PATH for these shell checks. Logs: `migration-gate-fix.txt` and `migration-docker-fix.txt` under `X:/DevTemp/rosy-d427/resume/`.

WSL Ubuntu, actual Jazzy environment sourced, `python3 -m unittest tools.gz.test_map_monitor -v` from middleware/perception: **1 test OK**, no skip; `map-monitor-ros.txt` in the same scratch directory. This is ROS-imported host logic, not ROS graph, simulation, device or field proof.

Independent reviewer `/root/d427_safety_review`: **APPROVE**, no source blocker. Independently ran **66 passed, 1 skipped** and actual Git Bash syntax exit 0, confirmed 29 launch files and unchanged single-publisher checks. Final enforced push gate, current remote-main alignment, CI and artifacts remain pending.
