# devices

**Parent context:** `../AGENTS.md`

Hardware-family assembly, profiles and adapters (D-625, D-626). Control algorithms and CORE authority have separate owners. Moving a holder does not create another final command publisher.

| Directory | Responsibility |
|-----------|----------------|
| `pinky/` | Bringup, physical description and Pinky Pro profile |
| `omx/` | OMX adapter, profile and agent composition; arm command ownership stays in the adapter |
| `rasptank/profile/` | Config-only RaspTank Metal source preparation; physical capabilities disabled, no driver or product activation |

ROS package names, ament share names and entry points stay unchanged. Read the family and package guides before editing. Tests run through `tools/remote/remote_pytest.py`; never run local pytest. Device activation and physical acceptance require their own evidence.
