## D-556 신선한 odom과 영상이 기억한 한쪽 경계의 차체 횡단에 동의하면 HOLD한다

**Status:** Proposed (2026-10-09, 2026-10-13 main으로 포팅). `lane_odom_veto_enabled: false`가 기본이다. 구현 후보와 호스트 시험만 있다. 실영상의 물리 경계 ID, ROS 폐루프, 장치·현장 수용은 없다. 배포와 현장 활성화의 근거가 아니다.

**10/7 재생 정정:** [MP4 비교](../validation/lane-odom-veto-2026-10-09/result.md)의 차이 0은 odom 자세가 없는 입력의 결과다. [원본 MCAP 재생](../validation/lane-odom-veto-2026-10-09b/result.md)은 신선한 odom 207/207프레임에서 후보가 140프레임을 추가 HOLD했다. 물리 경계 정답이 없어 정확도는 미확인이다. 기본 꺼짐을 유지하며, 경로 계획과 차선 공백을 잇는 작업은 D-531·D-476에서 검증한다.

잇는 결정: [D-364](D-364-lane-keeping-perception-and-replay-bench.md) (카메라 단독 keeper 기본 동작), [D-468](D-468-local-lane-departure-return.md) (이탈 복구), [D-476](D-476-lane-loss-expected-road-bridge.md) (도색 공백 bridge), [D-531](D-531-route-context-to-lane-keeper.md) (Fleet 경로 문맥), [D-475](D-475-human-reviewed-fixed-eval-truth.md) (사람 경계 검수), [D-597](D-597-drivable-keep-steering-source.md) (drivable 조향 법칙).

## 문제

`LaneKeeper`는 직전 프레임의 횡위치와 기울기로 한쪽 선의 side를 잠시 이어 쓴다. 로봇이 실제 그 선을 넘어갔어도 네 프레임 동안 과거 side가 남을 수 있고, 목표가 옆 차로로 향한다. 단순 `visible=false`로 내면 CORE의 D-476 bridge가 정상적인 도색 공백으로 보고 전진할 수 있다. Fleet 지도 자세는 차선 화소의 물리 ID가 아니며 0.5초 주기의 원격 조향 자료도 아니다.

## 후보 규칙

1. keeper는 영상 시각에 신선한 odom이 직전과 현재 프레임 모두에 있을 때만, 직전의 **실제로 선택된 한쪽 경계**를 현재 로봇의 읽기 위치로 옮긴다. 직전 선택 경계와 맞는 현재 후보가 하나뿐이어야 한다. 연속 pose 간 이동이 기존 `ODOM_MAX_STEP_M`을 넘거나 값이 유한하지 않으면 신규 충돌 판정은 하지 않는다. odom으로 예측한 선과 현재 영상 선이 모두 기억한 side의 반대편으로 10mm(`SIDE_CONFLICT_MARGIN_M`) 넘게 갔을 때만 `odom_side_conflict`로 HOLD한다. 새 차선이나 새로운 경계는 odom으로 승인하지 않는다.
2. 충돌 HOLD는 카메라 공백·노드의 keeper reset·`both` 판독을 지나도 이어진다. 벽의 흰 성분이 `both`로 오인된 기록이 있어서 자동 해제하지 않는다. 현 코드의 해제는 새 keeper 세션(노드 재기동)뿐이며 운영 복귀 절차가 없다. 실영상 검수와 독립적인 복귀 조건을 갖추기 전에는 이 옵션을 켜지 않는다.
3. keeper 충돌은 CAMERA_LINE의 `visible=false`, `confidence=0`, `quality.reason=odom_side_conflict`로 CORE에 보낸다. CORE는 저조도·과노출처럼 이 품질 실패에서 D-476 bridge, D-468 로컬 복구와 일반 회복을 거치지 않고 HOLD한다. CORE가 유일한 최종 `cmd_vel` 발행자다. 지도 호 주행(D-520)은 별도 안전 계약으로 이 keeper 사유를 사용하지 않는다.
4. 옵션이 꺼져 있거나 충돌 이력이 없는 상태에서 odom이 없거나 낡으면 D-364 카메라 단독 판정이 그대로다. 한 번 확인된 충돌의 HOLD는 이후 odom 소실로 해제하지 않는다. 이 규칙은 Fleet 계획을 없애거나 trip을 다시 시작하지 않는다. 경로 유지·재정위·재합류는 D-531 및 Fleet 후속 계약에서 검증한다.

## 포팅 메모 (2026-10-13)

원 브랜치 `fix/lane-odom-cross-veto`(78e599e5b, 7344e9624)를 현재 main 구조로 옮기며 규칙 1–4는 그대로 두고 아래만 바꿨다.

- **위치:** 판정은 `LaneKeeper` 안이 아니라 `middleware/perception/sensors/line_observation/keep_odom_veto.py`의 `OdomVetoLaneKeeper`(LaneKeeper 하위 클래스)에 있다. `lane_keep.py`는 파일 크기 한도(600줄)에 있어 한 줄도 바꾸지 않았다. 노드는 옵션이 켜졌을 때만 이 클래스를 만들고, 꺼져 있으면 기존 `LaneKeeper`를 그대로 만든다. 하위 클래스는 `LaneKeeper`가 그 프레임의 판독을 끝낸 뒤 그 기록을 본다. 그래서 `flipping` HOLD가 난 프레임에서는 충돌을 새로 판정하지 않는다(원 구현은 그 앞에서 판정했다).
- **D-597과의 관계:** drivable 조향 법칙이 켜져 있어도 옵션이 켜져 있으면 keeper 기록으로 충돌을 판정한다. 래치된 HOLD는 노드의 `CAMERA_LINE` 발행 직전에 적용되어 drivable 법칙이 낸 관측도 `visible=false`로 바꾼다. keeper 선을 조향에 쓰지 않는 법칙에서 이 판정이 맞는지는 검증하지 않았다.
- **CORE 쪽 관측:** `GET /api/v1/line-follow`의 `reason`은 `camera_odom_side_conflict`이고, `lost_after_s`가 지나면 저조도와 같이 LOST(`reselection_required`)와 `nav.lane_lost`(`reason: camera_odom_side_conflict`)가 된다. 모드를 다시 골라도 keeper 래치는 남는다(규칙 2의 공백).
- **재생:** `learning/evaluation/perception/road_replay.py --odom-veto`가 후보를 켠다. 기본 재생 출력은 그대로다. 포팅본으로 10/7 원본을 다시 재생하지 않았다.

## 검증과 승격 조건

- SOURCE: 좌·우 대칭 횡단에서 HOLD와 래치, 정지 odom 영상 흔들림에서 기존 추종, 충돌 전 odom 없음·stale·점프에서 기존 판정, 양쪽 선·굽이의 기본 판정, 경쟁 후보와 벽의 거짓 `both`에서 잘못된 승인 없음, 품질 사유의 CORE 수용과 진행 중 bridge·로컬 복구 거부를 시험한다. 기본 옵션 끔에서 노드 판단이 D-364와 같음을 확인한다.
- REPLAY: 10/6·10/7 원본의 동일 물리 경계, 가림, 재출현, 벽·분기를 D-475 사람 검수한 뒤 baseline과 비교한다. 잘못된 이어짐 0, 정상 추종 손실, flicker, consecutive miss, 목표 오차와 차체 여유를 함께 기록한다. odom 일치 자체를 정답으로 쓰지 않는다.
- SIM: 직선·굽이·한쪽 소실·벽·분기 폐루프에서 CORE 최종 명령과 정지·재획득을 확인한다. DEVICE/FIELD: 카메라 지면 투영과 odom·Rosy Cam 기준을 독립 확인한 뒤 별도로 수용한다.

**한계:** 정지한 벽은 odom과 일치할 수 있다. `both`도 벽의 흰 성분을 잘못 짝지을 수 있다. 이 규칙만으로 벽 오인식이나 Fleet trip의 자세 소실 후 복귀를 해결했다고 판정하지 않는다. 10mm 여유는 영상 쪽 허용치이며 로봇 형상(URDF)에서 나온 값이 아니다.
