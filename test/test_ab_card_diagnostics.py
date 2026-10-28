"""Read-only GPT card diagnostics require an explicit layout and root slot."""
import copy
import hashlib

import pytest

from test_card_diagnostics import _tool, FakeTree, _device_files
from test_sd_gpt_layout import _table_image


@pytest.mark.parametrize("provision_role", ["boot_a", "bootstrap"])
@pytest.mark.parametrize("slot", ["a", "b"])
def test_gpt_diagnostics_use_explicit_root_and_provision_roles(tmp_path, provision_role, slot):
    tool = _tool()
    raw, layout = _table_image(with_files=True)
    layout["provision_role"] = provision_role
    image = tmp_path / "card.img"
    image.write_bytes(raw)
    before = hashlib.sha256(raw).hexdigest()
    opened = []

    def open_tree(disk, offset, size):
        opened.append((offset, size))
        return FakeTree(_device_files())

    report = tool.extract(str(image), tmp_path / "out", open_tree, layout=layout, slot=slot)
    parts = {p["role"]: p for p in layout["partitions"]}
    root, boot = parts["root_" + slot], parts[provision_role]
    assert opened == [(root["start_lba"] * 512, root["size_lba"] * 512)]
    assert report["partitions"]["boot"]["offset"] == boot["start_lba"] * 512
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("case", ["missing_slot", "missing_layout", "bad_slot", "wrong_guid", "bad_backup"])
def test_gpt_diagnostics_refuse_ambiguous_or_changed_tables_before_ext4_reads(tmp_path, case):
    tool = _tool()
    raw, layout = _table_image()
    slot = "b"
    if case == "missing_slot":
        slot = None
    elif case == "missing_layout":
        layout = None
    elif case == "bad_slot":
        slot = "current"
    elif case == "wrong_guid":
        layout = copy.deepcopy(layout)
        layout["partitions"][4]["unique_guid"] = "734d3572-d8d9-4dde-b645-e1bac89b882d"
    else:
        raw[-512 + 16] ^= 1
    image = tmp_path / "card.img"
    image.write_bytes(raw)
    with pytest.raises(ValueError):
        tool.extract(str(image), tmp_path / "out", lambda *args: pytest.fail("must verify GPT first"),
                     layout=layout, slot=slot)
