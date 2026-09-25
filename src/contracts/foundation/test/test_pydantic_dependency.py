"""Runtime dependency contracts for shared CORE schemas."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_common_requires_pydantic_v2():
    package_xml = (ROOT / "package.xml").read_text(encoding="utf-8")
    setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")

    # Ubuntu 24.04's rosdep package is Pydantic 1.x.  Keep the ROS dependency
    # resolvable and express the v2 contract in Python/deploy requirements.
    assert '<exec_depend>python3-pydantic</exec_depend>' in package_xml
    assert 'version_gte="2.0"' not in package_xml
    assert "'pydantic>=2.0'" in setup_py
