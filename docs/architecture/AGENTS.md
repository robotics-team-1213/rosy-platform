
# architecture

**Parent context:** `../AGENTS.md`

## Purpose

Numbered target-OS architecture documents (v0.1) for ROSY Platform: a distributed robotics and physical-AI platform on Ubuntu 24.04 and ROS 2 Jazzy. They describe the target shape and migration path, not the current implementation state. `ROSY OS` stays the repository and historical artifact name (D-290).

## For AI Agents

### Working In This Directory

- Files are numbered `NN_ROSY_<Title>.md`; keep the number prefix and add new documents at the next number.
- Documents here are English. Binding decisions are ADRs in `docs/adr/` and the SRS in `docs/spec/`; when they disagree with these documents, the ADR wins.
- Do not state a target capability as accepted or shipped; acceptance evidence lives in `docs/validation/` and the gate files.
- Folder names in `src/` follow the layered layout checked by `test/architecture/`; update a document here when that layout changes, not the reverse.

### Testing Requirements

No test reads these files' prose. Run the document placement and layout guards after adding or moving files:

```bash
python3 -m pytest test/architecture/test_document_placement.py test/architecture/test_folder_layout.py -q
```

### Common Patterns

- Numbered chapters reference each other by number and by D-xxx ADR ids.

## Dependencies

### Internal

- `docs/adr/`, `docs/reference/ROSY ADR Log.md`, `docs/spec/`, `src/` layer roots
