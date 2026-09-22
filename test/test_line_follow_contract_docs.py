"""D-143 public REST and snapshot contracts stay documented."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_api_reference_documents_line_follow_endpoints_and_snapshot():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    assert "**Version:** v1.15" in reference
    assert "`/api/v1/line-follow`" in reference
    assert "`/api/v1/line-follow/mode`" in reference
    assert '"line_follow": {' in reference
    assert "IR_LINE" in reference
    assert "CAMERA_LINE" in reference
