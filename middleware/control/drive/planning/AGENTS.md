# planning

**Parent context:** `../AGENTS.md`

`nav2/` is the existing ROS package `navigation`: launch, params, maps, rviz and policy helpers. Its package/share/import identities stay unchanged (D-626). The standalone and composed launches must send smoother output to `nav_cmd_vel`, leaving CORE as final writer.

Tests: repository Nav2 launch, limits, footprint and bandwidth contracts through `tools/remote/remote_pytest.py`. Linux install/launch, ARM64 images and physical acceptance are separate evidence.
