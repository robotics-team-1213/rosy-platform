# control

**Parent context:** `../AGENTS.md`

Device control responsibilities (D-625, D-626). This holder differs from the historical ROS package `control`, whose sensor evidence lives in `middleware/perception`.

`drive/` holds existing base-control backends. CORE admits requests, arbitrates candidates and owns the final `/cmd_vel`; a backend must not bypass it. Arm command ownership remains in `middleware/devices/omx/adapter` until a separately reviewed responsibility extraction. Do not create placeholder Arm packages or another process.

Read the child guide and current manifest before changes. Use the remote test runner; local pytest and Gazebo are prohibited.
