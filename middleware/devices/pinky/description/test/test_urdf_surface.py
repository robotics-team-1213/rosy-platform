"""URDF surface for the description package (D-73)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_robot_xacro_declares_the_rosy_model():
    xacro = (ROOT / "urdf" / "rosy.urdf.xacro").read_text(encoding="utf-8")
    assert "robot" in xacro.lower()
    assert xacro.strip()
    package = (ROOT / "package.xml").read_text(encoding="utf-8")
    assert "<name>description</name>" in package
    assert "${namespace}${side}_wheel_joint" in xacro
    assert 'side="l"' in xacro
    assert 'side="r"' in xacro
