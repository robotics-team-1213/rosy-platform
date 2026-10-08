<!-- Parent: ../AGENTS.md -->

# AI PC inference and smoke units

This folder owns the AI PC's inference and deployment-smoke systemd user units. Independent model evaluation belongs to the Model PC (D-527). Install and verify these units on the AI PC; they are not part of the robot image or the site Fleet stack. The GPU timer reports driver failure. The Laya service remains disabled until an approved fixed model revision and GPU readback are checked. It binds to loopback and has no Fleet, ROS, or actuator authority (D-516).

Do not put credentials, host addresses, or evaluation recordings here. Store run evidence in `docs/validation/` and private scratch outside F:.
