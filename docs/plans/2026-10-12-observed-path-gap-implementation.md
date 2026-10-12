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
- 기하 반례 RED 12개, 소비 경계 RED 13개, 최신 거절/현재 odom/무효 기하 RED 9개와 odom 복귀 RED 1개를 원격에서 확인하고 수정했다. 직선 횡오프셋·좌우 곡선·실제 관측 age·누적거리·거절 우선권·RL gain 제외를 구현했다.
- 독립 SOURCE APPROVE. 구현 commit `afb9205c2`의 유효 자원 원격 회귀 498 PASS·1 SKIP·NEW 0이다. 초기 affected의 네 NEW는 preview fixture, ADR 번호 gap, 문서 commit 표기의 검사로 나뉘었고 같은 회귀에서 모두 수정 확인했다. 노트북에서 잘못 시작한 affected 실행은 중단·폐기했으며 자원 floor 미달 fallback 결과도 수용에 쓰지 않는다.
- 최종 구현·기록 commit `831d9bdc6`의 전체 affected 후속 검증은 자원 기준을 충족한 원격 PC에서 6,086 PASS·359 SKIP·NEW 0·terminal exit 0이다. 두 invocation은 이 세션의 `logs/affected-final/run-1.txt`, `run-2.txt`에 보존했다. lint는 0 errors·28 warnings다.
- 실제 Isaac 재실행, R29 최초 소실 해결, 이번 구현의 main 착지, push 및 실물 수용은 확인하지 않았다.
