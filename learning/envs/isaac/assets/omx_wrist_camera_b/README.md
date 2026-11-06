# 팀 손목(link5) 보이는 모양 — D 틀

손목 카메라 사례(`wrist_camera`)에서 link5의 순정 메시 대신 그린다(`stacking_scene.team_wrist_visual`). 순정 메시에는 ROBOTIS 카메라 틀 F9가 붙어 있어 B 렌즈 앞을 가린다.

- 출처: rosy-docs `hardware/omx-wrist-camera-mount` (브랜치 `docs/omx-wrist-cam-mount`, 커밋 a1b43e9), link5 좌표 mm.
  - `link5_gripper.stl`, `gripper_plate_F6.stl`: ROBOTIS 공식 OMX-AI Follower STEP에서 뽑은 부품(`extract_parts.py`).
  - `b16-u16-span-D-holder-assembly.stl`: 실제 출력한 D 틀 r06, 자리 뒤 16 · 옆 16 mm, 균형 기울기(11-07).
- 보이는 모양만 바꾼다. 충돌체는 그대로라서 틀이 이웃에 닿는지는 MuJoCo(`tools/sim/ship_v11_scene.py`)에서 본다.
- 카메라 자세는 `palletizing_gripper.WRIST_CAMERA_B`. 틀을 바꾸면 두 곳을 같이 바꾼다.
