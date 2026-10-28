"""SIM-only OMX Pilot owner: runtime facade over the single arm owner (``runtime``), gripper state
(``gripper``), FastAPI app (``api``), demonstration capture (``capture``), camera stream (``camera``)
and the ROS/uvicorn entrypoint (``server``, run as ``python3 -m omx_adapter.pilot_sim.server``).
Moved out of the flat ``omx_adapter`` package for D-766 (size unit)."""
