<!-- Parent: ../AGENTS.md -->

# AI PC inference and smoke units

This folder owns the AI PC's inference and deployment-smoke systemd user units. Independent model evaluation belongs to the Model PC (D-527). Install and verify these units on the AI PC; they are not part of the robot image or the site Fleet stack. The GPU timer reports driver failure. The Laya service remains disabled until an approved fixed model revision and GPU readback are checked. It binds to loopback and has no Fleet, ROS, or actuator authority (D-516). `rosy-signal-agent.service` (D-525 rev 4) is the one Fleet client here: it reads the Fleet traffic and guide views and only posts signal demands with a named operator token; it never commands a robot or changes a signal mode. `rosy-situation.service` (D-577) reads Fleet and posts facts and heartbeats as `ai_observer` only; install it only with the AI PC owner's consent.

Do not put credentials, host addresses, or evaluation recordings here. Store run evidence in `docs/validation/` and private scratch outside F:.
