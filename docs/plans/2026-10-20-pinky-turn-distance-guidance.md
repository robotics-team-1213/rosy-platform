# Pinky 연결점 거리 안내 Implementation Plan

상태: 사용자 승인 후 Task1의 관측 feasibility가 **NO-GO**로 판정됐다. Task2 이후의 새 protocol 구현은 진행하지 않는다. [검증 기록](../validation/pinky-junction-feasibility-2026-10-20/result.md)이 근거와 후속 기존 계약 내 수정을 소유한다. 아래 단계는 원래 제안의 기록이다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 각 단계의 증거를 확인하고 다음 단계로 진행한다. 독립 안전 리뷰는 별도로 받는다.

**Goal:** 같은 조건에서 실패한 코너의 연결점 거리 가설을 검증하고, 관측된 출구 선택에만 적용한 SIM 후보를 연속 2회 수용한다.

**Architecture:** Fleet이 선택 경로의 짧은 기하와 연결점을 같은 authority pose에 결합한다. CORE의 기존 선택·수명 경로를 거쳐 perception이 가능한 잔여 거리 구간을 계산하고, 구간 전체가 관측된 도달 범위 안일 때만 반대 재중앙화의 우선순위를 바꾼다. 초기 구현·활성화는 native Gazebo에 한정하며 운영에서는 새 필드를 생략한다.

**Tech Stack:** 기존 Python, Pydantic, NumPy, ROS 2/Gazebo, native remote pytest/SIM. 새 의존성 없음.

**Spec:** [승인한 설계](2026-10-20-pinky-turn-distance-guidance-design.md). 아래 기하 전달과 SIM 한정 범위는 설계의 미확정 보정 조건을 닫기 위한 추가 제안이며, 이 실행 계획 검토에 포함한다.

## Global Constraints

- 현재 runtime 기준은 검증 기록의 commit SHA `e434578bccbc938d2abb27cf6d5d319dd668aa83`이며 같은 소스 1 PASS/1 FAIL이다. 주행 수용 HOLD를 유지한다.
- `pivot_ok`는 계속 `Literal[False]`. CORE 최종 명령·clearance·HOLD/LOST·crosswalk·front-stop·정렬 예산·D-622의 trip 자동 REALIGN 거절을 유지한다.
- 지도 거리로 통로나 출구를 합성하지 않는다. heuristic 오차와 실측/모델에 근거한 오차 범위를 구별한다.
- 커밋된 SHA만 native 원격 시험한다. RED도 먼저 커밋한다. 로컬 pytest·Gazebo·실물 주행·main 착지·push는 이 계획 실행에 포함하지 않는다.
- 전제 실패는 중단 결과다. 단지 통과하려고 오차 범위를 줄이거나 회전 허용 범위를 넓히지 않는다.
- 각 소스 수정 전 파일·단위 크기를 확인한다. D-766 한도의 95% 이상이면 동작 불변 분리를 먼저 독립 관심사로 처리한다. foundation·Fleet·CORE·perception·SIM은 각각의 작업 브랜치/검토 단위로 나누고, 15개 초과 파일이나 FULL 선택은 분리 여부를 먼저 판단한다.

## Review Focus

| 입력/실패 모드 | 고정할 동작과 담당 단계 |
|---|---|
| 구버전 독자가 `next_junction: null`도 거절함 | 미활성 출력의 키 자체 생략, 단계 2·3 |
| 곡선·가까운 평행 차선에 여러 투영이 가능함 | 모든 가능한 station을 포함하고 경계가 애매하면 사용하지 않음, 단계 4 |
| 이전 정렬이 살아 있는 상태에서 같은 연결점 안내가 갱신됨 | 새 episode/예산으로 취급하지 않음, 단계 5 |
| 열린 영상 테두리의 출구가 실제 연결 통로와 단절됨 | 출구 이름이나 최대 전방 x만으로 도달 범위를 인정하지 않음, 단계 1·5 |
| 바인딩 없는 운영 pose 또는 모델/지도 교체 | 새 객체를 보내지 않고 기존 동작 유지, 단계 3·6 |

## 1. 실패 장면에서 거리 조건의 실행 가능성부터 확인

**읽을 파일:** `tools/sim/fleet_trips.py::fleet_console`, `tools/sim/native_gazebo_map_pose.py`, `middleware/devices/pinky/description/urdf/rosy_gz.urdf.xacro`, `operations/fleet/fleet/server/trips/trip_geometry.py::_pose_tol`, 기존 [검증 기록](../validation/pinky-corner-lifetime-2026-10-19/result.md).

**산출물:** 저장소 밖 `C:/DevTemp/pinky-success-baseline-20261019/turn-distance-feasibility/`의 `result.json`, 장면별 좌표·거리 표 및 SHA256. API 필드는 아직 추가하지 않는다.

- [ ] 기존 기록의 source frame/pose/prior를 93–97초 구간에서 동일 stamp로 결합한다. frame SHA256·지도/모델·source SHA를 확인한다. exact full-resolution mask가 없으면 원본 영상과 같은 ONNX로 native 호스트에서 재계산하고 **재계산 mask**로 표시한다. 4px RLE를 원본 mask로 간주하지 않는다.
- [ ] 현재 카메라에는 선택 경로 polyline이 없으며 keeper의 직선 `ds`를 station 증가량으로 사용할 수 없음을 재현한다. `_pose_tol`은 along-path heuristic이고 기본 최소 허용치가 0.12 m이므로 위치·yaw 오차의 물리적 한도로 전용하지 않는다.
- [ ] native Gazebo의 실제 `/odom` producer, `NativeGazeboMapPosePort`의 frame/map/clock 결합, 현재 pose 보간·외삽 구간을 확인한다. `/odom`은 현재 URDF에서 model-pose OdometryPublisher이며 wheel odom과 다르다. 이 사실을 실물·일반 localization 성능으로 확대하지 않는다.
- [ ] source 위치/yaw와 source→current odom의 위치/yaw 오차가 각각 어떤 SIM 모델/기록으로 제한되는지 표로 남긴다. 외삽·누락 odom·구간 중 gap은 새 분기에서 거절한다. 보간 구간의 오차는 0으로 가정하지 않는다. 해당 오차 범위가 근거를 갖지 못하면 여기서 중단한다.
- [ ] 가능한 잔여 거리 구간 전체가 0 이상이며 관측 경로 길이 하한 이내인 장면이 목표 코너에 존재하는지 계산한다. 특히 마지막 약 0.0284 m 장면만 선택하지 않고 앞선 진입 장면도 확인한다. 조건을 만족하는 장면이 없거나 기존 실패를 정확히 재현할 수 없으면 가설 보류로 보고하고 후속 제품 변경을 하지 않는다.

이 단계는 분석 결과가 GO인 경우에만 끝난다. NO-GO이면 기존 runtime과 HOLD 상태를 보존하고 근거를 사용자에게 보고한다. 미확정 오차 숫자를 후속 구현자가 선택하게 두지 않는다.

## 2. 기하를 포함한 계약 준비 — 별도 foundation 관심사

**수정:** `contracts/foundation/core_common/protocol/lane_route_guide.py`, `contracts/foundation/test/test_lane_route_guide_lifetime.py`, `contracts/foundation/setup.py`, `contracts/foundation/package.xml`, `docs/reference/ROSY API & Protocol Reference.md`. 관련 ADR은 구현 직전 정식 예약 도구로 번호를 받아 작성한다. 실제 foundation 버전과 고정 의존 버전은 예약 단계에서 검색하고 그 목록을 커밋 범위에 포함한다. 미래 버전을 미리 추측하지 않는다.

**인터페이스:** `NextJunction`은 설계의 `segment_index`, `s_m`, `heading_after_deg`에 `path`와 `error`를 더한다. `RouteStationPoint`는 유한한 `x_m`, `y_m`, `s_m`이며 source pose의 base 평면 좌표다. `RouteProjectionError`는 `source_position_m`, `source_yaw_deg`, `relative_odom_position_m`, `relative_odom_yaw_deg`의 네 비음수 유한 범위다. yaw 범위는 각각 180도 이하이고, 각 범위의 수치·적용 시간/모델 조건은 단계 1의 GO 증거에서 고정한다. 유효한 근거 없이 객체를 생성하지 않는다. 스키마 모듈은 `STATION_ROUNDING_M = 0.000050001`도 내보내며 Fleet의 같은 기존 상수와 perception 계산이 이를 함께 import한다.

`path`는 2–256점, 누적 station 엄격 증가, 전체 길이 2 m 이하이며 각 segment의 Euclidean 길이는 0보다 크고 station 차이와 기존 `STATION_ROUNDING_M` 이내에서 일치해야 한다. source station과 연결점 station을 포함한다. source 뒤쪽 최대 0.25 m와 기존 guide의 앞쪽 `ahead_m` 안의 선택 경로만 담는다. 원본 vertex를 보존하고 양 끝 절단점만 보간한다. 제한 초과 시 코너를 지우는 단순화를 하지 않고 객체를 생략한다.

- [ ] RED: `test_next_junction_is_atomic_and_strict`, `test_next_junction_path_has_metric_stations`, `test_next_junction_rejects_nonfinite_and_bool`, `test_absent_next_junction_key_is_not_serialized`를 추가한다. 기존 guide dict에 객체가 없어도 통과하고, null 객체의 직렬화 결과에는 키가 없으며, 부분 객체/역전 station/길이 불일치/257점/2 m 초과/NaN/bool은 거절함을 검증한다.
- [ ] RED commit 후 아래 원격 명령으로 의도한 실패를 확인한다. 두 guide 모델에 optional 객체와 null 키 생략 직렬화를 구현하고 동일 명령으로 GREEN을 확인한다.
- [ ] API reference와 ADR에 SIM 한정 사실·전체 수신자 선행 배포·모든 전달 경계의 키 생략·오차 근거·CORE 권한 불변을 기록한다. 독립 계약 리뷰 후 explicit 파일만 커밋한다. foundation 변경의 FULL 분류를 소비자 시험으로 대체하지 않는다.

```text
python tools/remote/remote_pytest.py --log-dir C:/DevTemp/pinky-success-baseline-20261019/turn-distance-contract -- contracts/foundation/test/test_lane_route_guide_lifetime.py -q
```

## 3. 선택 경로 생성과 기존 전달 경로

**수정:** `operations/fleet/fleet/routing/direction.py`, `operations/fleet/fleet/traffic/route_guide.py`, `operations/fleet/fleet/server/app.py`, `operations/fleet/fleet/server/trips/trip_runner.py`, `operations/fleet/fleet/server/trips/trip_steps.py`, `operations/fleet/test/test_route_direction.py`, `operations/fleet/test/test_trip_route_guide.py`, `middleware/drive/behaviors/line_follow/route_guide.py`, `middleware/core/services/test/test_authority_route_guide.py`, `middleware/core/gateway/core/bridge/lane_route.py`, `middleware/core/gateway/test/test_lane_route_publication.py`.

**인터페이스:** `selected_junction(graph, segments, index, s, pose_xy_yaw, *, error) -> dict | None`은 `NextJunction` 형식의 map/trip 사실만 반환한다. 기존 `route_direction`을 별도 최근접 차선 선택으로 바꾸지 않는다. source-local 변환은 `routing/graph.py`의 directed arc `polyline/knots/point_at`으로 계산하고 perception 코드를 import하지 않는다. `create_app`과 `TripRunner`에 내부 keyword `junction_projection_proof=None`을 추가한다. `create_app`은 기존 `deployment_profile == 'simulation'` 및 실제 port의 `validate_simulation_binding` 성공 뒤에만 proof를 수용한다. `TripSteps`가 이를 `record_guidance(..., junction_projection_proof=...)`로 넘긴다. 기본값은 끝까지 `None`이며 HTTP 입력이나 source 문자열로 설정할 수 없다.

- [ ] RED: `test_selected_junction_uses_reversed_selected_arc`, `test_selected_junction_ends_at_partial_destination`, `test_selected_junction_rejects_noncontiguous_or_free_space`, `test_junction_uses_same_authority_pose`, `test_operational_pose_omits_next_junction`으로 선택 경로/부분 목적지/불연속/TTL/source stamp/운영 미송신을 고정한다.
- [ ] `record_trip_guidance`의 기존 지도·pose·authority 검증 뒤에만 객체를 붙인다. 초기 활성화는 native SIM runner가 확인한 binding과 단계 1의 오차 근거를 모두 제공할 때만 허용한다. `pose.source` 문자열 하나나 일반 `line_follow_route_guide` capability만으로 활성화하지 않는다.
- [ ] `bind_guide`가 같은 source budget으로 객체를 복사함을 검증한다. `RouteGuidePublication`에서 null 키 생략·초기 clear·만료 clear·clock rollback·같은 source 반복 발행이 수명을 늘리지 않음을 고정한다. 운영 출력은 키 자체가 없어야 한다.
- [ ] 각 RED를 커밋해 native 원격에서 실패를 확인하고 최소 구현 후 같은 시험을 GREEN으로 확인한다. Fleet producer와 CORE 전달은 별도 모듈 관심사 커밋으로 나눈다.

## 4. 현재 pose의 가능한 station 구간 계산

**생성:** `middleware/perception/front_camera/perception/drivable/junction_guide.py`, `middleware/perception/test/test_junction_guide.py`.
**수정:** `middleware/perception/front_camera/perception/learned/paint_motion.py`, `middleware/perception/test/test_learned_paint_motion.py`, `middleware/perception/front_camera/perception/drivable/drivable_keep.py`, `middleware/perception/sensors/line_observation/line_observer_node.py`, `middleware/perception/test/test_drivable_guide_alignment.py`.

**인터페이스:** `OdomHistory.covered_poses(start_s, end_s) -> tuple[Pose, Pose] | None`은 전체 구간을 실제 samples로 감싸고 모든 gap이 기존 0.2 s 이하일 때만 두 pose를 반환한다. 기존 `pose_at`의 0.1 s 외삽 허용을 새 증거로 쓰지 않는다. `keep_step(..., pose_span=None)`의 keyword로 전달하며 기존 호출은 호환된다. `junction_interval(prior, source_pose, current_pose) -> tuple[float, float] | None`은 잔여 거리 하한/상한을 반환한다.

- [ ] RED: `test_curve_station_is_not_chord_distance`, `test_all_nearby_projection_stations_are_retained`, `test_station_scale_and_rounding_expand_error_outward`, `test_cropped_path_ambiguity_disables_junction`, `test_odom_gap_or_extrapolation_disables_junction`, `test_passed_junction_is_not_clamped_to_zero`로 목표 기하와 실패 조건을 고정한다. 첫 시험은 직각 두 segment의 총 진행 거리와 chord가 다름을 명시적으로 검증한다. station 길이가 좌표 길이보다 허용치만큼 큰 synthetic 사례에서도 가능한 station을 누락하지 않아야 한다.
- [ ] 현재 pose를 기존 SE2 변환과 같은 방식으로 source 좌표에 놓는다. source 위치 오차, 상대 odom 위치 오차와 source yaw 오차가 현재 변위에 만드는 원판 반경을 더해 보수적인 위치 반경 `eps`를 구한다. yaw에 의한 반경은 `2 * 변위길이 * sin(min(yaw오차, 180도)/2)`다. 각 segment에 대한 최근접 거리 `d_i`와 투영 station `t_i`를 구하고 `d_i <= min(d_i) + 2*eps`인 **모든** segment에서 station 반경 `eps * (Δs / L) + STATION_ROUNDING_M`을 적용한 구간을 segment 범위와 교차한다. 여기서 `L > 0`은 좌표 길이, `Δs`는 station 차이다. 거리 비교는 오차를 늘리는 방향으로, 구간 양 끝은 `math.nextafter`로 바깥쪽 반올림한다. 전체 구간의 최소/최대를 포함한 station 범위를 답으로 삼는다. 상대 odom 위치 오차는 해당 yaw 오차가 병진 변환에 미치는 효과까지 포함한 범위여야 한다. 단일 `argmin` 투영을 답으로 고르지 않는다.
- [ ] 계산 영역이 잘린 경로 경계 너머와 구분되지 않거나, station 역행/문맥 변경/만료/수치 오류가 있으면 `None`을 반환한다. 구간 중 하나라도 연결점을 지났다면 `None`이다. 경로 범위 밖 값을 clamp해 유효한 증거로 만들지 않는다.
- [ ] keeper는 source/current stamp와 route identity가 맞는 객체만 넘기고, `None`이면 기존 조향을 그대로 사용한다. 같은 연결점 메시지 갱신은 기존 정렬 예산을 초기화하지 않는다. RED commit→native RED→구현→같은 native GREEN 순서로 확인한다.

이 단계의 구간 알고리즘은 독립 안전 리뷰에서 synthetic 역방향·코너·평행 경로·경계 사례의 포함 관계까지 확인한다. 오차 영역을 어떤 방식으로 포함하는지 설명과 시험으로 제시하지 못하면 단계 5를 시작하지 않는다.

## 5. 실제 관측으로 입증된 출구에만 적용

**수정:** `middleware/perception/front_camera/perception/drivable/drivable_steer.py`, `middleware/perception/test/test_observed_recentre_alignment.py`, `middleware/perception/test/test_drivable_steer.py`.
**생성:** `middleware/perception/test/fixtures/pinky_nw_junction_recomputed.json` — 단계 1의 full-resolution mask RLE·정확한 stamp/pose/prior·이미지/모델 SHA256을 담고 재계산 여부를 명시한다.

**인터페이스:** `junction_observed(interval, connected_path_m, exit_point_m, heading_after_deg, *, junction_point_m, way, ground, x_offset, source_pose, current_pose, heading_error_deg) -> bool`을 `junction_guide.py`에 둔다. keeper는 prior path의 연결점 station을 보간해 `junction_point_m`을 current body 좌표로 변환한다. `DrivableSteer.update`는 keyword `junction_context=None`을 받고 유효한 결과를 `_update`의 기존 `recentre_first` 판단에만 사용한다. context에는 이 연결점 좌표, 잔여 거리 구간, current body 기준 다음 방향과 총 yaw 오차를 함께 넣고 source/current 검증 실패 시 전체를 `None`으로 만든다.

- [ ] RED: `test_recorded_nw_exit_is_not_overridden_by_opposite_recentre`가 기존 동일 mask/pose 입력의 잘못된 우선순위를 재현해야 한다. 기존 코드가 이미 통과하거나 새 조건이 그 장면에서 사용되지 않으면 회귀를 고쳐 꾸미지 말고 가설 재검토로 돌아간다.
- [ ] `test_disconnected_border_exit_does_not_authorize_junction`, `test_stale_or_opposite_exit_keeps_existing_guard`, `test_same_junction_does_not_recharge_alignment`, `test_crosswalk_front_stop_and_realign_remain_effective`를 추가한다. exit 이름·route memory·최대 전방 x만 있는 입력은 새 분기를 허용하지 않아야 한다.
- [ ] 현재 관측의 통로 path 각 segment와 출구를 source 영상으로 되돌려, near seed에서 이어진 같은 mask component 안에 있는지 raster 단위로 확인한다. 기존 ground↔pixel/SE2 변환을 재사용한다. 지도 연결점도 이 관측 경로와 연결되어야 한다. path의 양 끝 Euclidean 거리를 실제 연결 경로 길이의 보수적인 하한으로 사용한다. 이것은 누적 경로 길이의 추정치가 아니라 그 하한이며, 최대 전방 x를 하한으로 쓰지 않는다. 잔여 거리 구간 전체가 0 이상이고 이 하한 이내인지 검사한다. 기존 출구 방향 허용 범위를 재사용하되 source/상대 odom yaw 오차 전체에서도 일치해야 한다. 양 조건을 통과하면 반대 `recentre_first`만 억제한다. realign timer나 CORE 정지 판단을 리셋/완화하지 않는다.
- [ ] `drivable_steer.py`가 현재 574 LOC로 600 LOC 한도의 95%를 넘으므로, 여기에 추가하기 전에 동작 불변 분리 브랜치를 먼저 준비한다. `way_target`과 그 전용 기하·상수를 `drivable/way_target.py`로 옮기고 기존 import/re-export와 반환값을 유지한다. 새 모듈이 drivable_steer를 역으로 import하는 순환은 만들지 않는다. 해당 크기 guard와 기존 drivable 회귀를 별도 SHA로 통과·검토하고, 필요한 선행 착지 권한은 사용자에게 별도로 받는다. 한도를 넘는 기능 추가로 우회하지 않는다.
- [ ] native RED/GREEN 후 독립 안전 리뷰를 받는다. 진단에는 source/current station 구간·연결점 identity·오차 근거·관측 path 길이·선택/거절 이유를 기존 debug 경로로 남긴다.

## 6. 같은 배포 묶음의 native SIM 수용

**수정:** `tools/sim/fleet_trips.py`, `test/test_fleet_trips.py`.
**기록:** 새 날짜의 `docs/validation/` 결과. 기존 실패 결과를 고쳐 쓰지 않는다.

- [ ] SIM runner의 명시적 실험 옵션 `--junction-guide`를 추가한다. 기본은 비활성이다. 활성화는 검증된 native binding·단계 1 오차 근거·동일 source의 foundation/CORE/gateway/perception 묶음이 있을 때만 허용한다. 미지원/불명 상대에게는 null을 포함해 필드 자체를 보내지 않는다. 운영 활성화 설정은 추가하지 않는다.
- [ ] `test_junction_guide_requires_native_complete_bundle`, `test_default_bench_omits_junction_field`로 누락 binding·혼합 source·모델/지도 교체·기본 비활성을 검증한다. pytest는 아래처럼 committed SHA로 원격 실행하고 각 로그를 known failures와 비교한다. 같은 basename의 capture 시험은 별도 invocation으로 분리한다.
- [ ] `rosy_harness.py affected --base <candidate-base>`와 `size_range.py`로 단계별 선택/크기 게이트를 확인한다. foundation FULL, 관련/affected, 독립 리뷰를 모두 통과해야 SIM 수용으로 넘어간다. main이 움직였다는 이유로 미시험 변경을 후보에 섞지 않는다.
- [ ] 아래 조건의 native SIM을 같은 SHA로 2회 연속 실행한다. 둘 다 목표 코너에서 새 분기의 실제 사용과 통과를 기록해야 한다. 사용하지 않은 성공은 가설 수용 증거가 아니다. 실패·비활성 이유·모델 범위 이탈도 그대로 보존한다.
- [ ] zero fallback, goal/via, 최종 명령·odom 정지, lease 해제, 소유 프로세스 잔존 없음과 native fetch/STOP/CLEANUP을 확인한다. 성공해도 `lane_return` 제외 및 native model-pose 기반 SIM 조건, 실물·현장 미검증을 표시한다.

```text
python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- <owned-test-paths> -q
python test/known_failures.py <external-log-dir>/run-1.txt
python -X utf8 tools/remote/remote_sim.py --host model --sha <source-commit> --log-dir <external-run-dir> --minutes 60 fleet_trips -- --render gpu --learned-lane-pointer /home/rosy/rosy-test/v2-sim-lap/model-pointer.txt --learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return --junction-guide
```

## 실행 전 확인

진행 방법은 이 세션에서 직접 구현하고 마지막에 독립 안전 리뷰를 받는 **Native**를 권장한다. 기하 계약·좌표 보정·동일 장면 회귀가 밀접하게 연결되어 있어 구현 담당을 자주 바꾸는 이점이 작다. 먼저 이 계획과 추가 제안(SIM 한정, 경로 조각 전달)을 검토받는다. 승인 전에는 제품 코드나 실제 API 계약을 바꾸지 않는다.
