"""The module inventory remains closed when a new Console view is extracted."""

import pytest
import test_document_imports as contract


@pytest.mark.parametrize("module", ["roster-presentation.js", "integrated-control-view.js"])
def test_install_cannot_import_console_roster_presentation(monkeypatch, module):
    original = contract._imports

    def imports(name):
        return original(name) | ({module} if name == "install.js" else set())

    monkeypatch.setattr(contract, "_imports", imports)
    with pytest.raises(AssertionError, match=r"install\.js.*" + module.replace(".", r"\.")):
        contract.test_each_console_document_reaches_only_its_modules()
