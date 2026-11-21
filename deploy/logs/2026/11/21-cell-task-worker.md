## 2026-11-21 · uncommitted · cell task worker와 팔 세션 래퍼를 관리 릴리스로 옮김

- 변경: rosy-omx-cell-task-worker.service가 omx-devices/current에서 돌고 R은 rosy-fleet-r.local·r-site-ca.pem; 세 팔 세션 래퍼와 tools-env.sh를 deploy/robot/omx/session-wrappers로 올려 TOOLS_ROOT에서 OMX·PYTHONPATH를 만듦; cell_task_exec가 릴리스 래퍼를 띄우고 TOOLS_ROOT를 넘김; services.yaml 선언을 autoupdate로
- 증거: 로컬 test_omx_cell_worker_release.py, test_omx_cell_task_exec_measured.py, test_omx_tier_fusion.py, test_host_services_manifest.py
- gate 변화: 실물 적용은 팔 세션이 없을 때 deploy/robot/omx/README.md 순서로
- 결정: 없음
- 교훈: 없음
