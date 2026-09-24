"""D-143 public REST and snapshot contracts stay documented."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_api_reference_documents_line_follow_endpoints_and_snapshot():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    # Version pin moves with every doc MINOR bump (PRT-006). Keep it at the
    # header version so a silent version freeze fails here.
    header = [line for line in reference.splitlines() if line.startswith("**Version:**")]
    assert header and "v1.19" in header[0], (
        "API Ref header version moved — update this pin in the same change")
    assert "`/api/v1/line-follow`" in reference
    assert "`/api/v1/line-follow/mode`" in reference
    assert '"line_follow": {' in reference
    assert "IR_LINE" in reference
    assert "CAMERA_LINE" in reference
