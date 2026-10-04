import math

import pytest

from fleet.server.cell_app_store import CellAppStore, DocumentChanged


def test_documents_survive_restart_and_require_current_digest(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = CellAppStore(path)
    saved = store.save("recipe", "two-layers", {"schema": "recipe/1"}, expected_digest=None)
    restarted = CellAppStore(path)
    assert restarted.get("recipe", "two-layers") == saved
    with pytest.raises(DocumentChanged):
        restarted.save("recipe", "two-layers", {"schema": "other"}, expected_digest=None)
    updated = restarted.save("recipe", "two-layers", {"schema": "other"}, expected_digest=saved["digest"])
    assert updated["digest"] != saved["digest"]
    assert restarted.list()[0]["digest"] == updated["digest"]


@pytest.mark.parametrize("kind,identifier,document", [
    ("other", "valid", {}), ("cell", "../escape", {}),
    ("recipe", "valid", {"value": math.nan}), ("recipe", "valid", {"data": "x" * 65536}),
])
def test_invalid_documents_are_not_written(tmp_path, kind, identifier, document):
    store = CellAppStore(tmp_path / "fleet.sqlite3")
    with pytest.raises(ValueError):
        store.save(kind, identifier, document, expected_digest=None)
    assert store.list() == []
