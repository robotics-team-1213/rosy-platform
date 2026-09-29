"""Minimal ament marker for the Isaac Sim asset tree (D-322).

This is not a buildable ROS package — it carries URDF worlds and Python
probes only. The marker exists so the D-168 structure scan and harness
see it as a package rather than an invisible directory (the honest-hole
note in `test/architecture/test_module_structure.py` was removed when
this landed). Declared deps are intentionally empty.
"""

from setuptools import setup

package_name = "isaac_sim"

setup(
    name=package_name,
    version="0.1.0",
    packages=[],
    data_files=[],
)
