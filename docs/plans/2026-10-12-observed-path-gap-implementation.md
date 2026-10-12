# Observed Path Gap Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 관측한 직선·곡선 형상을 유지하고 현재 odom으로 공백 목표를 재계산한다.

**Architecture:** 기존 `way_target`의 중심점 계산과 `ExpectedPath`를 재사용한다. 저장 경로와 현재 제어 출력을 분리하고 같은 추론은 기억의 시각을 갱신하지 않는다. Isaac에서 출처와 RL 제외를 명시하며 CORE 게이트를 유지한다.

**Tech Stack:** Python, 기존 numpy, ROS-free 원격 pytest.

### Task 1: 기하와 예산의 실패 시험

`middleware/perception/test/test_expected_path.py`, `test_drivable_steer.py`, `learning/envs/isaac/test/test_camera_lane.py`에 접선·곡선·관측 시각·누적거리 반례를 넣고 커밋한다. `tools/remote/remote_pytest.py --log-dir <X session>/logs/red -- <해당 시험>`으로 RED를 확인한다. 자원 floor 미달 fallback은 수용에 쓰지 않는다.

### Task 2: 관측 형상 유지

`drivable/drivable_steer.py`에서 연속·유한·전방 중심점을 내보낸다. `learned/expected_path.py`는 polyline을 odom에 저장하고 실제 접선으로 확정하며 현재 pose에서 투영·거리 목표·기존 pursuit error를 계산한다. 시간과 누적 이동은 마지막 독립 관측 기준이다. `drivable_keep.py`에서 source/current pose를 나누어 전달하고 최신 거절은 기억보다 우선한다.

### Task 3: 소비 경로와 검증

`lane_debug.py`는 여러 점을 그린다. `tools/sim/isaac/camera_lane.py`는 검증된 held 경로 출처를 받아들이며 `run_map_rl.py`는 이를 RL에서 제외한다. 관련 기존 시험의 직선 전용 가정과 시간 기준을 D-708에 맞춘다. 커밋된 HEAD의 관련 원격 시험과 known_failures, harness lint를 확인하고 독립 코드 검토를 받는다. main 착지·push·배포·실물 수용은 별도 요청과 증거에 따른다.

### 진행

- 계약과 구현 계획 작성 완료.
- RED, 구현, GREEN, 독립 검토는 진행 중.
