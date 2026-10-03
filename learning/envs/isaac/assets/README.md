# Isaac Sim robot model sources

| Robot | Model files | Official source | Revision | License |
|---|---|---|---|---|
| Pinky Pro | [`src/sim/description/`](../../../../src/sim/description/) (19 meshes and ROSY xacro) | [pinklab-art/pinky_pro](https://github.com/pinklab-art/pinky_pro/tree/014a09f289e6988894fbffde2624fdb1e257815b/pinky_description) | `014a09f289e6988894fbffde2624fdb1e257815b` | Apache-2.0 |
| OMX-F and OMX-L | [`open_manipulator_description/`](open_manipulator_description/) (two expanded URDFs, 15 STL meshes, license) | [ROBOTIS-GIT/open_manipulator](https://github.com/ROBOTIS-GIT/open_manipulator/tree/0a4af6a923b8b7d80b8c20506d1839c54d2e993e/open_manipulator_description) | `0a4af6a923b8b7d80b8c20506d1839c54d2e993e` / release 5.1.2 | Apache-2.0 |

The Pinky Pro source was downloaded to an external scratch directory and compared with the checked in model. All nine collision STL and four of ten visual DAE files match SHA-256 exactly. Six visual DAE files (`base_link`, `camera_assy`, `front_camera_mount`, `main_wheel`, `rplidar_c1`, `screen_assy`) differ from that upstream revision. The existing ROSY xacro and meshes remain the model imported by `prepare_urdf.py`; no second copy of the 23 MB Pinky geometry is stored here.

The OMX snapshot contains the vendor's expanded `.urdf` files and every STL they reference. The vendor xacros pull in Gazebo and hardware control definitions; the expanded URDFs are the appropriate geometry-only starting point here. `manifest.json` records the SHA-256 of every copied vendor file. `prepare_omx_urdf.py` checks each mesh reference and writes absolute file URIs for Isaac's importer. This snapshot does not imply that OMX is mounted on Pinky or that either arm's command, camera, or physical calibration is accepted.
