# 서쪽 차선 접근부 정지 원인 분리 (2026-10-10b)

## 질문과 입력

[앞선 몸체·페인트 감사](../lane-bend-map-footprint-2026-10-10/result.md)는 D-507 Gazebo의 나중 서쪽 출발 10회가 굽이 전에 모두 LOST이고 `body_gap_m`이 0 부근이라고 기록했다. 그 값이 **현재 로봇 몸체와 맵 벽의 실제 거리**인지 검증했다. `body_gap_m`의 계약은 진행 경로를 따라 예상하는 첫 접촉 거리다(`line_follow/clearance.py:body_path_gap`); 정지 자세의 벽 거리와 같은 양이 아니다.

입력은 모델 PC에서 읽기 전용으로 복사한 이전 `runs/fwest_01`–`fwest_10`의 `log.jsonl`, SHA-256 `cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b`인 260919 STL, 이전 모델 PC 작업공간에서 복사한 SIM URDF·메시다. 현행 코드의 ROS-SIM 재실행은 아니다. 과거 빌드와 복사한 URDF의 동일성을 입증하는 서명은 없다.

재현: `python docs/validation/lane-west-approach-2026-10-10b/evidence/wall_gap.py --urdf-root X:/DevTemp/lane-bend-map-audit-20261010/old_repo X:/DevTemp/lane-bend-map-audit-20261010/runs`. 스크립트는 각 실행의 마지막 `obstacle_ahead` 중 `body_gap_m`이 있는 GT 자세를 고르고, URDF 충돌 형상 hull에서 STL 내부 벽면까지의 최단 평면 간격을 계산한다. 실행별 수치는 [wall-gap.json](evidence/wall-gap.json)에 기록했다. 원본 로그는 `X:/DevTemp/lane-bend-map-audit-20261010/runs`에만 둔다.

## 관측과 판정

- 10회 모두 마지막 정지 자세의 STL 벽 간격은 **63.0–72.1 mm**였다. 같은 기록의 `body_gap_m`은 **0–25.5 mm**, 전방 IR은 모두 `[600, 600, 600]` mm였다. 따라서 `body_gap_m≈0`을 실제 벽 접촉으로 해석한 이전 문서의 표현은 부정확하다. 이 수치는 경로 예측과 센서 점으로 계산한 정지 근거이며, 벽과의 정적 간격이 아니다.
- `fwest_01`의 마지막 주행 명령 `[0.0188 m/s, +0.48 rad/s]` 직후 정지한 GT에서는 STL 벽을 점으로 샘플해 현행 `body_path_gap`에 넣었을 때 0.4 m 경로 안의 벽 접촉을 찾지 못했다(`X:/DevTemp/lane-bend-map-audit-20261010/wall_check.py`). 이는 **현행 함수로 한 진단**이며, 과거 실행의 정확한 LiDAR 스캔·기억점·제어 바이너리를 재생한 결과가 아니다.
- 과거 probe는 API에 있는 `clearance_source`와 `stop_gap_m`, 원시 LiDAR 점을 `log.jsonl`에 남기지 않았다. 그러므로 벽 경로 예측, LiDAR 반사, 기억점 또는 다른 물체 중 어느 것이 마지막 정지를 만들었는지는 이 로그로 결정할 수 없다. 장애물 게이트를 완화할 근거도 없다.

다음 SIM에는 같은 버전의 소스·URDF·맵 해시와 함께 `clearance_source`, `stop_gap_m`, 첫 접촉을 만든 스캔 점/기억점, 명령 전후 시각을 기록한다. 먼저 서쪽 정지의 출처를 특정하고, 그 뒤 같은 시작 자세 10회에서 STOP 보존과 굽이 진입 여부를 비교한다. 이 기록은 SIM 진단이며 장치·현장 주행 수용이 아니다.
