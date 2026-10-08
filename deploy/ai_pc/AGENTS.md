<!-- Parent: ../AGENTS.md -->

# AI PC evaluation units

This folder owns only the AI PC's offline evaluation systemd user units. Install and verify on the AI PC; these files are not part of the robot image or the site Fleet stack. The GPU timer reports driver failure. The Laya service remains disabled until a fixed model revision and GPU readback are checked. It binds to loopback and has no Fleet, ROS, or actuator authority (D-516).

Do not put credentials, host addresses, or evaluation recordings here. Store run evidence in `docs/validation/` and private scratch outside F:.
