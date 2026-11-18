"""D-1039: the cell's AI assessor clears with its own token file, named outside the operator token glob."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import omx_incident_fleet as fleet  # noqa: E402


def test_assessor_token_file_is_used_and_an_explicit_operator_file_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("ROSY_OPERATOR_TOKEN_FILE", raising=False)
    monkeypatch.delenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", raising=False)
    cfg = tmp_path / ".config/rosy"
    cfg.mkdir(parents=True)
    (cfg / "cell-a-operator-op7.token").write_text("op\n")
    assessor = cfg / "cell-a-ai-assessor.token"  # not matched by *-operator-*.token, so the glob still finds one
    assessor.write_text("ai\n")
    assert fleet.default_token_file() == cfg / "cell-a-operator-op7.token"
    monkeypatch.setenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", str(assessor))
    assert fleet.default_token_file() == assessor
    monkeypatch.setenv("ROSY_OPERATOR_TOKEN_FILE", str(cfg / "cell-a-operator-op7.token"))
    assert fleet.default_token_file() == cfg / "cell-a-operator-op7.token"
