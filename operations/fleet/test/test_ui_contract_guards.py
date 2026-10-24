"""The module inventory remains closed when a new Console view is extracted."""

import pytest
import test_document_imports as contract


def test_install_cannot_import_console_roster_presentation(monkeypatch):
    original = contract._imports

    def imports(name):
        return original(name) | ({"roster-presentation.js"} if name == "install.js" else set())

    monkeypatch.setattr(contract, "_imports", imports)
    with pytest.raises(AssertionError, match=r"install\.js.*roster-presentation\.js"):
        contract.test_each_console_document_reaches_only_its_modules()
