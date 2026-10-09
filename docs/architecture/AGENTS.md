<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# architecture

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Numbered target-OS architecture documents (v0.1) for ROSY Platform: a distributed robotics and physical-AI platform on Ubuntu 24.04 and ROS 2 Jazzy. They describe the target shape and migration path, not the current implementation state. `ROSY OS` stays the repository and historical artifact name (D-290).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Principles, initial platform, profiles, and reading order |
| `00_ROSY_OS_Vision_and_Definition.md` | Vision and definition |
| `01_ROSY_OS_Target_Architecture.md` | Target architecture |
| `02_ROSY_Domain_Model.md`, `03_ROSY_Runtime_Architecture.md` | Domain model, runtime |
| `04_ROSY_Device_Adapter_Specification.md`, `05_ROSY_ROS2_Interface_Specification.md`, `06_ROSY_Device_State_and_Lifecycle.md` | Device adapter, ROS 2 interfaces, lifecycle |
| `07_ROSY_Capability_Model.md`, `08_ROSY_Task_and_Workflow.md`, `09_ROSY_Composite_Robot.md` | Capabilities, tasks, composite robots |
| `10_ROSY_Compute_Fabric.md`, `11_ROSY_AI_and_Physical_AI.md`, `12_ROSY_Dataset_and_Learning_Pipeline.md` | Compute, AI, datasets |
| `13_ROSY_Current_to_Target_Migration.md` | Current-to-target migration plan |
| `14_ROSY_Verification_and_Acceptance.md`, `15_ROSY_Ubuntu_Modular_Installation.md`, `16_ROSY_Interface_Design_Principles.md` | Verification, installation, interface principles |

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

### External

None.
