# 변경 이력

## v2 — 2026-09-20

### 변경

- 원본 주석의 명목 치수와 실제 SDF box 치수 차이를 명시했습니다.
- Physics system의 DART 엔진 파일을 지정했습니다.
- 물리 프로파일 이름 `track_1ms` 추가, `type="dart"`로 표현을 정렬했습니다.
- 점유 지도를 원본과 동일한 5 mm 정책으로 재생성했습니다.
- 도면의 주석을 v2 검토 내용으로 정리했습니다.
- 셀 경계 오차 설명을 “한 셀 미만”이라는 단순 표현 대신 “한 셀 대각선 이내의 보수적 경계 확장”으로 보완했습니다.
- 기본 Nav2 패치, RPP 선택 패치, Progress 선택 패치를 분리했습니다.
- 실제 전체 YAML을 기반으로 새 시뮬레이션 파일만 준비하는 도구를 추가했습니다.
- 주의사항, 파라미터 표, 시험 체크리스트, 결과 기록 양식 및 정적 검사를 추가했습니다.

### 유지

- 원본 `world name`, `model name`, link 및 벽 이름
- 모든 모델의 pose·geometry·visual·collision·material·surface
- 16개 벽의 두께 10 mm·높이 155 mm, 통로와 고립 X pocket
- 1 ms timestep, 원본의 rate/real-time 목표값, 바닥과 GUI 설정
- 지도 원점·크기·해상도·픽셀 분류·외부 unknown 정책

### 적용 보류 / 미확인

- 현재 실제 로봇의 URDF·footprint와 사용자 전체 Nav2 YAML
- 실물 벽 치수·마찰·LiDAR 높이
- 실제 안전설정·하드웨어 guard 구현·모터 명령 경로
- vendor launch 수정·시뮬레이션 startup gate 구현
- Gazebo/ROS/Nav2 실행 검증 및 실기 승인

이번 패키지의 파일 생성은 위 항목의 구현·실행·승인을 뜻하지 않습니다.
