## D-612 인식 맹점은 녹음에서 태어나고 같은 녹음의 재생으로만 닫는다

**Status:** Accepted (2026-10-10, 사용자 지시: 횡단보도와 주행 가능 영역의 맹점을 계속 잡고 고치는 목록을 만들고, 시험한 뒤 로컬 main에 착지. 센서 전환, 로봇 플래그, right_exit_way 연결은 하지 않는다. SOURCE와 호스트 테스트만. 장치 수용이 아니다.)

### Context

- 주행 페인트는 LaneUNet이다. 실물 모델 `lane-seg-20261010-71edcb6d`(D-599)는 320×240의 112–239행만 칠한다. 9dfk의 실측 pitch·height에서 그 맨 위 행은 렌즈 앞 약 0.30 m다. 그보다 먼 갈림, 고리 출구, 횡단보도는 배경이 된다.
- 같은 날 재생(`docs/validation/drivable-branch-replay-2026-10-10.md`, 녹화 `20261009T073835Z`)에서 오른쪽이 기대인 230장 중 14장만 오른쪽을 골랐다. `right_exit_way`는 175장으로 올리지만 11,896장 중 4,634장의 길을 바꾸고 직선 차로를 자르므로 연결하지 않았다.
- 횡단보도 클래스는 ignore다. `drivable_target`은 ignore를 길로 다시 칠한 뒤 경계 페인트에서 줄무늬를 찾는다. 막대가 없어 줄무늬 검출은 비고, 같은 추론의 클래스 마스크만 남는다(D-597 개정 1, 녹화 `20261010T015707Z`).
- 구역은 `crosswalk_uncertainty_m`과 가로 `uncertainty_m`이 상한 안일 때만 선다. 9dfk는 `crosswalk_uncertainty_enabled`가 기본 꺼짐이고, pitch·height override에 `override_bounds`가 없어 `geometry_error`가 None이다. 게이트는 켜져 있어도 카메라 구역이 없다. 이 변경에서 그 플래그를 켜지 않는다.
- 한 차선만 보인다는 이유로 차선 IR을 횡단보도 선택기로 쓰지 않는다. 막대는 한 차선 안에 있다. 테이프에 맞춘 `detect_ir_line`(min_white 0.55)은 막대 반사 약 1700을 못 보고, 가운데만 밝은 위상은 차선과 같으며, 좌우만 밝은 두 띠는 관측 없음이다(D-491). IR은 이미 연 구역을 몸 아래에서 확인할 수 있을 뿐 앞을 고르지 못한다.
- D-578은 `keeper_logic`, `geometry_calibration`, `camera_exposure`를 인식 문제 목록으로 보낸다. 그 목록의 파일이 없었다. D-480 sim2real 목록은 시뮬과 실물의 차이고, 이 맹점과 섞지 않는다.

### Decision

1. **맹점 목록은 sim2real의 옆이다.** `tools/harness/perception_gaps.yaml` 한 행이 맹점 하나다. `rosy_harness.py lint`가 검사하고 `generate`가 `docs/reference/perception-gaps.md`를 쓴다. sim2real 행을 여기 넣지 않고, 여기 행을 sim2real에 넣지 않는다.
2. **태어남과 닫힘.** `born`은 녹음 id(`YYYYMMDDThhmmssZ`), `device:YYYY-MM-DD`, 또는 저장소 안 `.md`다. `replay`는 저장소 파일 또는 `unbuilt`다. CLOSED는 `validated_by`와 저장소에 있는 재생이 있어야 하고 `unbuilt`일 수 없다. 같은 녹음의 재생 수가 움직인 커밋에서만 행을 닫거나 고친다.
3. **후보는 채택된 센서처럼 보이지 않는다.** `kind: candidate`는 HOLD 또는 CLOSED만 된다.
4. **첫 네 행.** P-01 가까운 바닥만 칠함(OPEN, 재생 `tools/drivable_branch_replay.py`). P-02 ignore를 길로 다시 칠함(OPEN, 재생 없음). P-03 9dfk가 구역을 내지 않음(OPEN, 장치 읽기 2026-10-10). P-04 차선 IR은 횡단보도 선택기가 아님(candidate HOLD).
5. **D-578의 목록은 이 파일이다.** 그 루프가 라벨 후보가 아닌 원인을 내면 사람이 이 목록에 행을 더한다. 루프가 이 파일을 스스로 고치지 않는다. 학습 루프를 새로 만들지 않는다.

### Consequences

주행 코드, 로봇 overlay, `right_exit_way` 연결, IR 판정은 이 결정으로 바뀌지 않는다. 목록이 있어도 로봇은 그대로 달린다. 호스트 시험은 행이 형식에 맞는지만 본다. 장치 수용, 8kcn 확인, 맹점을 닫는 재생은 각각 다음 행의 일이다.

**Related:** [D-480](D-480-sim2real-three-tiers-and-gap-registry.md), [D-491](D-491-ir-guard-crosswalk-zone.md), [D-578](D-578-lane-failure-analysis-loop.md), [D-597](D-597-drivable-keep-steering-source.md), [D-599](D-599-drivable-model-team-crop128.md).
