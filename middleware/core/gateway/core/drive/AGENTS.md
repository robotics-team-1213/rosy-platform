# CORE Drive composition

**Parent context:** `../AGENTS.md`

D-627: assemble existing Drive managers inside CORE. `CoreServices` keeps its public attributes, common authority and listener registration order. No new process, service container, mode, hardware access or final command publisher.

| File | Responsibility |
|------|----------------|
| `line_follow.py` | Existing line-follow config, manager construction and envelope, floor-policy, sensor and stuck-recovery bindings |
| `docking.py` | Dock seed/config, docking and swarm assembly, Nav2 cancellation, docking mode take/release and mode-exit callback |
| `traffic.py` | Existing traffic-policy config/construction and explicitly bound measured-light observer validation/start |

Algorithms remain in `core_features`; Nav2 backend lives at `middleware/drive/planning/nav2`; ROS adaptation remains in `core.bridge`. The old `core.line_follow_wiring` and parser exports in `core.services` are compatibility facades. Avoid putting Arm or general system/power responsibility here.

These implementation files are Safety-tracked. Preserve cancellation, MANUAL admission, docking-lock release, E-stop callbacks, recovery defaults, body/envelope and candidate slots. Review a change independently before its first commit. Remote tests cover docking mode/release/listener isolation, goal generations, cmd_vel/port, line-follow body/recovery and Safety behavior. Installed wheel discovery is covered by `test/test_structure_installed_packages.py`. These checks do not establish ROS/device/field acceptance.
