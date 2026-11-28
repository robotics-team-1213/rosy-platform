
# Robot measurement tools

**Parent context:** `../AGENTS.md`

Only device/ir_line_calibrate.py remains here (sensor calibration); device/hotpath_measure.py moved to ../../drive/tools/device (it benchmarks drive's OccupancyMap and watches the control processes). Host simulation rigs live in ../../../tools/sim/gazebo; calibration migration in ../../../tools/calibration; static ROS inventory in ../../../tools/validation/audit_ros_names.py. Preserve existing measurement/calibration approval gates; no runtime nodes import these tools.
