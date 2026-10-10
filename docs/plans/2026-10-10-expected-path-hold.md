# Expected path hold Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** drivable keep가 매 카메라 프레임마다 오돔 위의 예상 경로 하나를 다시 내고, 차선과 drivable이 비어도 그 경로를 이동량만큼 옮겨 가까운 방향으로 조향을 이어 간다.

**Architecture:** 경로 가설은 perception의 순수 모듈이 소유한다. 새 마스크는 그 가설을 교체하지 않고, 가까운 방향이 맞을 때만 갱신한다. 공백 동안 CORE에는 신선한 `line/observation`을 보내 FOLLOW가 유지되므로 D-476 브리지는 시작하지 않는다. 같은 공백을 두 번 잇지 않기 위해서다. 화면에 보이는 선은 `line/keep_debug`와 기존 디버그 패널의 경로다.

**Tech Stack:** Python, numpy 없는 순수 기하, 기존 `line/observation` 계약, `line/keep_debug`. ROS 없는 호스트 시험은 시험 PC의 `tools/remote/remote_pytest.py`로만 돌린다(D-584).

**Status:** pending approval. 이 문서는 계획이다. 승인 전에는 제품 코드를 고치지 않는다.

---

## 결정

매 제어에 쓰이는 카메라 프레임은 예상 경로를 한 번 다시 계산해 낸다. 이번 프레임에 drivable 길이 없으면 직전 경로를 오돔 이동량만큼 옮겨 같은 주제로 다시 낸다. 조향점은 그 경로의 가까운 접선이고, 먼 끝점은 믿을 수 있는 길이의 상한이다.

이 연장은 직선으로 받아들인 구간에서만 한다. 제자리 회전, 출구 회전, 횡단보도, 선 위에 걸친 몸, 앞이 막혀 출구도 없는 경우에는 내지 않는다.

근거는 이 세션의 토론과 공개된 테슬라 설명이다. 2021 AI Day의 feature queue는 속도·가속도로 옛 특징을 옮긴 뒤 경로를 다시 예측한다. 2022 FSD 10.11은 차선을 벡터 공간의 점 나열로 다시 쓴다. 화면의 파란 선은 이번 프레임의 페인트가 아니라 그 예상 경로다. v12의 픽셀에서 조향을 바로 내는 구조는 가져오지 않는다.

## 지금 코드

- `drivable_keep.keep_step`은 길이 `WAY_MAX_AGE_S`(1.5 s)보다 오래되면 조향을 내지 않고 `drivable_way_stale`을 남긴다(`middleware/perception/control/sensing/perception/drivable_keep.py:31-48`). `DrivableSteer.lost`의 1.5 s는 래치만 지우고 마지막 목표를 쫓지 않는다(`learned/drivable_steer.py:273-278`).
- CORE는 관측이 `stale_after_s`(0.3 s)를 넘으면 HOLD, `lost_after_s`(3.0 s)를 넘으면 LOST다(`line_follow/model.py:88-89`, `manager.py:613-616`, `735-742`).
- D-476 브리지는 `line_not_visible`·`observation_stale`·`no_observation`이고 직전 추종이 안정적일 때만, 몸 진행 방향을 0.10 m까지 순항, 0.25 m까지 절반 속도로 잇는다(`lane_bridge.py:22`, `model.py:246-248`). 기본은 꺼져 있고 Status는 Proposed다. drivable 마스크가 죽는 순간은 대개 이 무장 조건 밖이다.
- D-476 결정 6: 브리지가 켜진 동안 perception이 `visible = true`로 같은 공백을 한 번 더 잇지 않는다. 이 계획은 그 반대로, perception이 신선한 관측을 유지해 브리지가 시작되지 않게 한다. `lane_bridge.py`는 고치지 않는다.
- 신뢰는 선속도에 곱해진다. `min_confidence` 0.35일 때 배율은 `(confidence - 0.35) / 0.65`다(`manager.py:398-405`).
- `keep_debug_payload`는 keeper `last`를 그대로 싣는다(`lane_debug.py:34-44`). 디버그 그림은 관측 전용이다(`lane_debug.py:3-4`).
- D-597 개정 2는 길이 없을 때 테이프 keeper로 조향을 되돌리지 않는다. 8kcn에서 그 복귀가 길과 싸웠다(`drivable_keep.py:45-48`). 이 계획도 그 복귀를 열지 않는다.

## 범위 밖

- v12식 끝단 신경망, occupancy, autoregressive 차선 그래프.
- 먼 끝점을 pure pursuit 목표로 쓰기.
- 좌우 래치를 더 오래 붙잡기. 출구는 지금처럼 몸 옆에 온 뒤에만 확정한다(`EXIT_NEAR_M`).
- CORE 브리지 무장 조건, `GET /line-follow` 필드, 대시보드 신규 화면.
- 회전·갈림·횡단보도·선 위 몸에서의 공백 연장.
- 장치 주행과 기본값 켜기. 첫 조각은 호스트 시험과 디버그 표시까지다.

## 경로 가설

모듈 `middleware/perception/control/sensing/perception/learned/expected_path.py`. ROS 없음. numpy 없음.

한 가설은 오돔에 둔 가까운 중심 `(x, y)`, 접선 heading(rad, 왼쪽이 양), 길이 상한 `length_m`, 확정 여부다.

확정 조건은 연속 3프레임이다(`bridge_arm_frames`, `lost_resume_frames`와 같은 수). 그 프레임들의 가까운 heading 차이가 12° 이하고(`road_state.py:37`의 양쪽 경계 평행 게이트), 그 틱의 전략이 `drivable_centre`일 때만 확정한다. 길이 상한은 `min(그 프레임의 ahead_m, 0.25)`다. 0.25 m는 `bridge_slow_m`이고, 경계 기억이 남기는 최대 거리와 같다.

공백 틱:

- 확정된 직선이고, 소실 뒤 오돔 이동이 `length_m` 미만이고, 경과가 2.5 s 미만이면 유지한다. 2.5 s는 `lost_after_s - bridge_time_margin_s`다.
- 조향점은 로봇을 그 중심선에 투영한 곳에서 heading 방향으로 0.10 m(`bridge_lookahead_m`) 앞이다. 끝점이 그보다 가까우면 끝점까지다. `error = -y / lane_half_width_m`. y는 현재 몸 좌표의 왼쪽이 양이다.
- 이동 0.10 m 미만의 신뢰는 0.90이다. 그 이후는 0.68이다. 0.68은 위 배율로 약 0.51이라 절반 속도에 대응한다. 시험이 이 배율을 `manager.py`의 식과 같은 식으로 고정한다.
- 예산이 끝나거나 아래 금지에 걸리면 관측을 내지 않는다. 그때부터 지금의 HOLD·LOST가 맡는다.

새 프레임:

- 가까운 heading이 가설과 12° 안이면 가설을 그 프레임으로 갈아 끼우고 이동 거리를 0으로 둔다. 상태 `live`.
- 어긋나면 그 프레임은 버리고 가설을 유지한다.
- 서로 같은 새 heading을 3프레임 연속 가리키면 가설을 교체한다.
- `drivable_pivot_*`, `drivable_turn_*`, `drivable_off_line_*`, `drivable_crosswalk_straight`, `straddle`, `drivable_closed`, `way_beyond_line`이면 그 틱에 가설을 버린다. 이 경우의 조향은 지금의 `DrivableSteer`가 낸 값을 그대로 쓴다.

속도는 시간 상한에만 들어간다. 예산의 본체는 미터다. 제자리 회전 공백은 가설을 만들지 않으므로 미터 예산으로 회전을 연장하지 않는다.

## 태스크

### Task 1: 경로 가설 시험

**Files:**

- Create: `middleware/perception/test/test_expected_path.py`
- Create: `middleware/perception/control/sensing/perception/learned/expected_path.py`
- Test: `middleware/perception/test/test_expected_path.py`

**Step 1:** 실패하는 시험을 쓴다. 포즈는 `(x, y, yaw)`다.

- 같은 heading의 `drivable_centre` 3프레임 뒤에만 `committed`가 된다. 2프레임은 아니다.
- heading이 12°를 넘는 프레임은 확정 줄을 끊는다.
- `drivable_pivot_right`와 `straddle`이 있는 틱은 가설을 비운다.
- 확정 뒤 길이 없는 틱은 `state == "held"`와 `error`를 낸다. 로봇이 heading 방향으로 0.05 m 가면 목표의 몸 좌표 y는 0에 가깝다.
- 조향 y는 끝점 y가 아니라 0.10 m 앞 접선의 y다. 끝점을 옆으로 0.20 m 치워도 held error는 변하지 않는다.
- 오돔 이동이 `length_m` 또는 0.25 m에 닿거나 경과가 2.5 s를 넘으면 `error is None`이고 `state == "dropped"`다.
- 이동 0.05 m의 신뢰는 0.90, 0.15 m의 신뢰는 0.68이다. `(0.68 - 0.35) / 0.65`는 0.45와 0.55 사이다.
- 가설과 20° 다른 한 프레임은 held를 유지한다. 그 새 heading이 3프레임 연속이면 `live`로 바뀐다.

**Step 2:** 시험 PC에서 돌린다.

```text
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/expected-path -- middleware/perception/test/test_expected_path.py
```

기대: 수집 실패가 아니라 테스트 실패(`expected_path` 없음). 닿는 PC가 없으면 착지하지 않고 그 사실을 적는다.

**Step 3:** 위 계약을 만족하는 최소 모듈을 쓴다. 공개 함수는 `ExpectedPath.update(pose, stamp, info)`와 `ExpectedPath.hold(pose, stamp)`다. `info`는 지금 `way_target`이 내는 `ahead_m`, `near_centre_m`, `strategy`, `straddle`, `reason`만 읽는다.

**Step 4:** 같은 원격 시험을 다시 돌리고 `python test/known_failures.py X:/DevTemp/expected-path/run-1.txt`로 비교한다. `NEW`가 없어야 한다.

**Step 5:** 이 두 경로만 커밋한다.

```text
git add middleware/perception/control/sensing/perception/learned/expected_path.py middleware/perception/test/test_expected_path.py
git commit -m "feat: hold a straight expected path across a missing frame"
```

### Task 2: keep_step에 연결

**Files:**

- Modify: `middleware/perception/control/sensing/perception/drivable_keep.py:24-48`
- Modify: `middleware/perception/test/test_drivable_steer.py` 옆의 keep 시험. keep_step 시험이 없으면 `middleware/perception/test/test_drivable_keep.py`를 만든다.
- Test: 그 시험 파일

**Step 1:** 실패하는 시험을 쓴다.

- 신선한 길이 있고 전략이 `drivable_centre`이면 지금의 error를 그대로 내고, `last["expected_path_state"] == "live"`이며 `expected_path_m`은 몸 좌표 두 점이다.
- 그 확정 뒤에 `latest_way`가 None이면 error를 낸다. `strategy`는 `expected_path_held`다. 테이프 keeper 분기로 떨어지지 않는다.
- 확정이 없기 전에 길이 없으면 지금처럼 `(None, False)`와 `drivable_way_stale`이다.
- 횡단보도 직진 틱 직후 길이 없으면 연장하지 않는다.

**Step 2:** 원격 pytest로 실패를 확인한다.

**Step 3:** `keep_step`이 길이 있을 때는 `steer.update` 결과의 `info`로 `ExpectedPath.update`를 부른 뒤, 그 error를 낸다. 길이 없을 때는 `hold`가 error를 주면 그 error와 신뢰로 `(error, confidence), True`를 반환하고 `last`에 `strategy=expected_path_held`, `expected_path_state=held`, `expected_path_m`, `expected_path_s_m`을 넣는다. error가 없으면 지금의 stale 반환을 유지한다. `line_observer_node.py`의 keep 분기는 `keep_step`의 반환만 쓰므로 노드 분기를 늘리지 않는다(`line_observer_node.py:534-544`).

**Step 4:** 원격 pytest와 `known_failures` 비교. 기존 `test_drivable_steer.py`도 같이 돌린다.

**Step 5:** 고친 시험과 `drivable_keep.py`만 커밋한다.

### Task 3: 디버그 패널에 경로를 그린다

**Files:**

- Modify: `middleware/perception/control/sensing/perception/lane_debug.py:187-206`
- Test: `middleware/perception/test/test_lane_debug.py`

**Step 1:** `expected_path_m` 두 점이 있는 `last`로 `render_debug`를 호출하면 반환 이미지에 그 선분의 픽셀이 칠해져 있다는 시험을 쓴다. 점이 없으면 그 픽셀은 배경이다.

**Step 2:** 원격 pytest로 실패를 확인한다.

**Step 3:** `render_debug`가 paint가 없어도 bev 패널을 만들고, `_bev_pixel`로 `last["expected_path_m"]` 선분을 그린다. 색은 기존 팔레트의 노랑이다. `keep_debug_payload`는 `last`를 복사하므로 새 키를 위한 인자 추가는 없다. 토픽 이름과 CORE API는 그대로다.

**Step 4:** 원격 pytest와 `known_failures` 비교.

**Step 5:** `lane_debug.py`와 그 시험만 커밋한다.

### Task 4: ADR

구현으로 이 태스크에 들어가기 직전에 번호를 선점한다.

```text
python tools/harness/adr_reserve.py next "expected path hold across a missing drivable frame"
```

**Files:**

- Create: `docs/adr/D-nnn-expected-path-hold.md` (선점된 번호)
- Modify: `docs/reference/ROSY ADR Log.md` 한 행. UTF-8 BOM, CRLF.

ADR은 이 계획의 「결정」과 「범위 밖」을 본문으로 한다. Status는 Proposed, 기본 동작 변경은 drivable keep이 켜진 로봇에 한정한다고 적는다. D-476과의 관계는 한 줄이다. 공백의 주인은 이 가설이고, 브리지는 그 가설이 관측을 내지 않은 뒤의 기존 경로로 남는다. D-597 개정 2의 테이프 복귀 금지를 유지한다고 적는다.

Log 행은 자신의 행만 `git apply --cached`로 올린다. ADR 파일과 Log 행은 한 커밋이다. 이어서 `python tools/harness/rosy_harness.py lint`를 돌린다.

### Task 5: 재생으로 공백 길이만 확인

코드 변경은 없다. 호스트 시험이 통과한 뒤에, 모델 PC에서 이미 녹화된 keep 프레임으로 `ExpectedPath`만 재생한다. 지표는 두 개다.

- 길이가 1–2프레임 비는 직선 구간에서 `held`가 나오고, 그 구간의 오돔 이동이 0.25 m를 넘기기 전에 `live`로 돌아오거나 `dropped`가 된다.
- 제자리 회전, 횡단보도, 선 위 몸이 있는 프레임 뒤에는 `held`가 0건이다.

재생 로그는 `X:\DevTemp\expected-path\`에 둔다. 이 지표가 깨지면 상수를 넓히지 않고 태스크 1의 금지 조건을 고친다. 로봇에 올리는 일과 `bridge_enabled`를 켜는 일은 이 계획 밖이다.

## 위험

- 틀린 직선 가설을 0.25 m 연장하면 선 밖으로 나간다. 완화는 확정 3프레임, 12° 게이트, 회전·횡단보도·선 위에서의 즉시 폐기, 0.25 m와 2.5 s 상한이다.
- 신뢰 0.68은 `min_confidence`가 바뀌면 절반 속도가 아니게 된다. 태스크 1의 배율 시험이 그 어긋남을 실패로 만든다.
- 신선한 held 관측은 CORE 손실 시계를 시작하지 않는다. 예산이 끝난 뒤의 빈 프레임부터 0.3 s·3 s가 센다. 브리지와 동시에 잇지 않는 이유가 이것이다.
- 오돔이 튀면 옮겨 둔 경로가 틀린다. 포즈 시각이 역행하거나 한 틱 이동이 0.25 m를 넘으면 가설을 버린다. D-468 무효화와 같은 방향이다.

## 검증

시험 PC:

```text
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/expected-path -- middleware/perception/test/test_expected_path.py middleware/perception/test/test_drivable_steer.py middleware/perception/test/test_lane_debug.py
python test/known_failures.py X:/DevTemp/expected-path/run-1.txt
```

노트북 pytest와 Gazebo는 돌리지 않는다. 호스트 통과는 장치 수용이 아니다. 착지와 푸시는 사용자가 말한 뒤에만 한다.
