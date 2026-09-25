"""D-182: policy code does not carry the sim partition or domain literals."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "src" / "sim" / "gz_sim" / "config" / "simulation_actuation.yaml"
TREES = (
    ROOT / "src" / "runtime" / "core_features" / "core_features" / "safety",
    ROOT / "src" / "runtime" / "core" / "core" / "bridge",
    ROOT / "src" / "runtime" / "navigation",
)
FORBIDDEN = ("pinky_calmap227", "'227'", '"227"')


def _sources():
    for tree in TREES:
        for path in tree.rglob("*.py"):
            if "test" in path.parts:
                continue
            yield path


def test_policy_trees_have_no_sim_identity_literals():
    hits = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}:{token}")
    assert hits == []


def test_sim_identity_lives_only_in_the_profile_and_safety_does_not_name_it():
    text = PROFILE.read_text(encoding="utf-8")
    assert "pinky_calmap227" in text
    assert "227" in text
    safety = (ROOT / "src" / "runtime" / "core_features" / "core_features" / "safety" / "manager.py").read_text(encoding="utf-8")
    assert "simulation_actuation.yaml" not in safety
    assert "ROSY_SIMULATION_ACTUATION" in safety
