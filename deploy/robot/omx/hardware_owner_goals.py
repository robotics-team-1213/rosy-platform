"""D-977 Decision 4: the hardware owner's local device_trial goals config and the field carry behind it.

The owner config may carry one ``arm_goals`` section. Without it the owner reports ``goals_enabled: false`` and refuses
every goal. With it (for exactly the arm this owner serves, plus a commissioning record) the owner accepts ARM_TRANSFER and
runs the reviewed folded carry on the separate arm session: ``cell_transfer.Gate`` and ``transfer_folded`` over the session
FIFO, no new motion code. The source/target names of a grant select a library a person reviewed (``cell_auto_pick`` /
``write_library``); an unknown pair is refused before anything moves.

  "arm_goals": {"device_trial_arms": ["<instance_id>"], "installation": "<written installation.json>",
                "installation_spec": "<device spec, schema rosy.sim-transfer-installation/1>",
                "cell_config": "<cell_auto_pick --config file of this arm>",
                "libraries": {"source>target": "<reviewed library.json>"}, "presence_token": "<local token file>"}

``--commissioning`` and ``person_at_switch`` are set for a carry only when ``presence_token`` is a fresh single-use file
a person created at the cell (rosy_agent.presence_token); no wire message can set them.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

SECTION_KEYS = {"device_trial_arms", "installation", "installation_spec", "cell_config", "libraries", "presence_token"}


def parse(section, *, instance_id: str, commissioning_root) -> dict | None:
    """None without a section; otherwise the section, or ValueError. Run by --check, so a bad file never starts."""
    if section is None:
        return None
    if not isinstance(section, dict) or set(section) != SECTION_KEYS:
        raise ValueError(f"arm_goals must hold exactly {sorted(SECTION_KEYS)}")
    if section["device_trial_arms"] != [instance_id]:
        raise ValueError("device_trial goals must name exactly the one arm this owner serves")
    if commissioning_root is None:
        raise ValueError("device_trial goals need commissioning_root (the owner must report device: true)")
    libraries = section["libraries"]
    if (not isinstance(libraries, dict) or not libraries
            or any(not isinstance(k, str) or k.count(">") != 1 or not isinstance(v, str) for k, v in libraries.items())):
        raise ValueError("arm_goals.libraries must map 'source>target' to reviewed library files")
    for path in (section["installation"], section["installation_spec"], section["cell_config"],
                 section["presence_token"], *libraries.values()):
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError("arm_goals paths must be absolute")
    return section


def load_installation(section):
    """The owner side of the written installation, checked against it (as run_cell_owner does)."""
    import transfer_installation as ti
    written = json.loads(Path(section["installation"]).read_text(encoding="utf-8"))
    installed = ti.owner_installation(ti.load(section["installation_spec"]), written["policy_digest"])
    if (installed.bindings.catalog.digest, installed.bindings.revision) != (
            written["policy"]["catalog_digest"], written["policy"]["bindings_digest"]):
        raise ValueError("the written installation was built from another catalog")
    return installed


def field_modules():
    """The field carry's code, imported late: it needs cv2/numpy and the arm's cell files."""
    import cell_arm_cal  # noqa: F401  (config loading imports it)
    import cell_attempts
    import cell_calibration
    import cell_pipeline as cp
    import cell_pivot
    from cell_auto_safety import Guarded
    from cell_auto_setup import open_cell
    from cell_transfer import FOLDED, Gate, transfer_folded
    return SimpleNamespace(open_cell=open_cell, Guarded=Guarded, Gate=Gate, FOLDED=FOLDED, transfer_folded=transfer_folded,
                           fold=cp.fold, attempts=cell_attempts, calibration=cell_calibration, pivot=cell_pivot)


def open_carry_for(section, *, field=None, presence=None):
    """-> open_carry(grant) for rosy_agent.arm_session_carry.ArmGoals. `field` and `presence` are injectable for tests."""
    from rosy_agent.arm_session_carry import Carry, CarryRefused
    if presence is None:
        from rosy_agent.presence_token import consume as presence
    libraries = dict(section["libraries"])

    def open_carry(grant):
        body = grant.arm_transfer
        library = libraries.get(f"{body.source}>{body.target}")
        if library is None:
            raise CarryRefused("no reviewed library for this source and target")
        f = field or field_modules()
        person_present = presence(section["presence_token"])
        args = SimpleNamespace(config=Path(section["cell_config"]), dry_run=False, task_id=None, handoff_lease_id=None,
                               want_object=None, want_colour=None)
        config, fifo, calibration_path, _work = f.open_cell(args, person_present)
        gate = f.Gate(f.Guarded(fifo, config), config, f.pivot.with_site_maps(config, f.calibration.load(calibration_path)),
                      sequence=f.FOLDED)
        held = gate.open(library, lambda assessment: f.attempts.begin(config, assessment))
        if held is not None:
            raise CarryRefused(f"held: {held.get('reason')}")
        return Carry(cell=gate, run=lambda cell: f.transfer_folded(cell, library, sequence=f.FOLDED),
                     fold=lambda: f.fold(fifo), sequence=tuple(f.FOLDED))
    return open_carry


def build(settings, *, field=None, presence=None):
    """ArmGoals for build_hardware_owner, or None when the owner config has no arm_goals section."""
    section = settings.arm_goals
    if section is None:
        return None
    from rosy_agent.arm_session_carry import ArmGoals
    return ArmGoals(load_installation(section), open_carry_for(section, field=field, presence=presence))
