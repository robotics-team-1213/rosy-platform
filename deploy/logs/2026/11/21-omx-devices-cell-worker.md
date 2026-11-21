## 2026-11-21 · uncommitted · omx-devices 릴리스가 cell worker 가져오기 닫힘을 모두 담음

- 변경: omx-devices-autoupdate.json.example paths의 omx_adapter 낱개 파일을 omx_adapter 패키지 전체로; smoke가 kinematics·area_xyz·z_profile·pose_plan을 가져옴; README 적용 순서에 live 설정 갱신·릴리스 확인 단계
- 증거: 로컬 test_omx_devices_release_covers_worker.py(ast 가져오기 닫힘 261파일 vs paths), test_chunk_library.py, test_structure_installed_packages.py, test_omx_arm_status_bridge.py, test_omx_cameras.py
- gate 변화: live 설정은 사람이 README 2단계로 고침
- 결정: 없음
- 교훈: 없음
