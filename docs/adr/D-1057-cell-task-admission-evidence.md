## D-1057 셀 작업 허가 증거는 지금 실제로 측정되는 값으로만 공급한다

**Status:** Accepted (2026-11-20, 사용자 결정 (가): 가드가 요구하는 증거를 "지금 실제로 측정되는 것"으로 공급하고, 측정이 없으면 기존 거부가 그대로 나게 한다). 독립 리뷰 대기(조정 세션). 실물·현장 수용은 별도다.

잇는 결정: [D-430](D-430-safety-as-a-separate-concern.md)(안전 변경과 `Safety-Review:`) · [D-911](D-911-omx-native-reviewed-operating-envelope.md)(OMX 승인 운전 범위).

### D-427 · D-429 · D-430 관계표

| 기준 ADR | 유지되는 계약 | D-1057에서의 변경 |
|---|---|---|
| D-427 (파트 소유) | Fleet은 `operations/fleet`, 팔 실행은 `deploy/robot/omx` 소유 | 새 최상위 폴더 없음. Fleet `sitemap` holder에 파일 하나 추가 |
| D-429 (관심·포트) | 최종 Base 명령은 CORE, 관절 실행은 OMX owner, 작업 전이는 Fleet | 변경 없음. 증거 공급자는 읽기만 하고 명령을 내지 않는다 |
| D-430 (safety) | 가드 한계값과 거부 코드는 안전 판단이다 | `_ready_amr`와 `complete_cell_task` 검사 코드는 바꾸지 않는다. 증거를 공급하는 쪽만 연결한다 |

### Context

`install_pipeline_routes`의 `amr_evidence_fn`과 `omx_evidence_fn`은 운영 코드에서 한 번도 연결된 적이 없었다. 그래서 claim은 `AMR_BRAKE_BED_VELOCITY_UNMEASURED`, 완료는 `OMX_OWNER_EVIDENCE_UNAVAILABLE`로 늘 거부된다. 거부가 맞는 동작이었지만, 두 증거를 실제로 만드는 입력이 없었다. 값을 흉내 내서 연결하면 가드가 약해지므로, 지금 측정되는 값만 연결하고 없는 값은 없다고 적는다.

### Decision

#### 1. AMR 증거 (`amr_evidence`)

| 필드 | 실제 원천 | 없거나 오래되면 |
|---|---|---|
| `robot_id`, `cell_id` | Fleet 원장의 작업 | 해당 없음 |
| `pose` | `MapPoseService.arbitrated_pose`. 활성 지도 ID가 있어야 하고, 그 지도·그래프에 셀 정차 지점이 실제로 있어야 한다(`resolve_omx_cells`의 기본 좌표로 만든 셀은 쓰지 않는다). LOCALIZED이고 앵커 출처가 sighting·pin·peer(odom으로 이은 `bridged` 제외)이며 `age_s` 2 s 이하, 활성 지도와 같은 `map_id`, 셀 정차 구역(사이트 지도 station 좌표에서 0.18 m 이내, `CELL_CLAIM_RADIUS_M`와 같은 값) 안일 때만 | None |
| `wheel_brake_locked` | CORE가 heartbeat로 보고하는 **정지 유지**: 모드 IDLE, navigation이 IDLE·ARRIVED·CANCELED·FAILED뿐(주행 진행 없음), 이 로봇의 Fleet 목표 없음, E-stop 아님, odom 선속·각속도가 임계(1e-4 m/s, 1e-3 rad/s) 이하. 표본마다 속도 채널 `received_at`이 heartbeat 도착 시각과 2 s 이내여야 하고, 이런 표본이 표본 간격 2.5 s 이하로 1 s 이상 이어져야 한다. **기계식 브레이크가 아니다.** 브레이크 센서는 없다 | heartbeat가 없거나 2 s보다 오래되면 None. 표본이 부족하면 False |
| `v_cmd_mps` | **명령 속도 원천 없음.** CORE는 명령 속도를 Fleet에 내놓지 않는다. 그래서 odom 선속(`StateSnapshot.velocity.linear`)과 CORE 모드로 대체한다. 값은 odom 0(정지)이며 명령값이 아니다. 명령은 냈지만 바퀴가 아직 움직이지 않은 순간은 속도로 가려낼 수 없으므로, 모드 IDLE이고 주행 진행(navigation)과 Fleet 목표가 없는 표본만 인정해 배제한다. 사용자 결정 (가)의 "정지 상태(속도 0)" 범위이며, 조정 세션이 이 대체를 확인했다 | 채널이 fresh가 아니면 None |
| `bed_ready` | 이름 있는 운영자가 작업마다 남기는 확인(`POST .../bed-confirm`). 유효 120 s, 확인 뒤 자세가 2 cm 넘게 움직이면 무효. bed 센서는 없다 | 확인 없음·만료·이동은 False |
| `observed_at` | 쓴 실시간 관측 중 가장 오래된 시각(heartbeat 도착, 속도 채널 수신, 지도 자세 관측). 운영자 확인은 자기 만료가 있어 실시간 관측에 넣지 않는다 | 하나라도 없으면 None |

판정 문턱 숫자(1 s, 2.5 s, 1e-3 rad/s, 120 s, 2 cm)는 이 ADR이 정한 값이다. 정지 표본은 0.5 s마다 heartbeat를 읽는 스레드가 쌓는다. 요청 때만 읽으면 claim과 완료 사이의 움직임을 놓친다.

#### 2. OMX owner 증거

Fleet은 `POST /api/fleet/pipeline/cell-tasks/{task_id}/owner-evidence`(proposer 권한)로 `receipt`, `stage_result`, `hardware_telemetry`를 먼저 저장한다. 그 셀의 owner로 등록된 서비스 주체만 보낼 수 있다(사이트 설정 `ROSY_FLEET_CELL_OWNERS=cell_s=id1,id2;cell_ab=id3`, 설정이 없으면 403 `OWNER_PRINCIPAL_NOT_REGISTERED`). 완료 요청도 저장 기록을 등록한 주체와 같아야 한다. RUNNING 작업이고 본문 `handoff_lease_id`가 원장 lease와 같고 `measured_at`이 claim 이후 60 s 이내이며 `hardware_telemetry.measured_at`과 2 s 안에서 같아야 한다. 본문은 64 KB까지다. 작업이 COMPLETED·CANCELLED·ABORTED가 되거나 기록이 만료되면 저장소에서 지운다. `omx_evidence_fn`은 이 저장 기록만 돌려준다. 완료 요청 본문을 복사해 돌려주지 않는다. 저장 후 60 s가 지나면 쓰지 않는다. 같은 lease에 같은 증거를 다시 보내면 한 건이고, 다른 증거는 409다.

셀 쪽은 `cell_auto_pick`의 `attempts[].verify`(새 상부 프레임 확인)를 `verification.placement`에 싣고, `folded`는 마지막 이동 단계가 settled 상태의 `park`이고 관절 readback이 설정 `plan.home`에서 3.0 이내(`chunk_runner_guards.SETTLE_TOL`와 같은 값)일 때만 참으로 한다. 측정이 없으면 `False`이고 Fleet이 `UNVERIFIED_CELL_COMPLETION`으로 거부한다.

**알려진 공백:** `cell_auto_pick`은 측면·상부 구역 측정(`cell_area_zones`)을 내놓지 않는다. 그 결과가 `attempts[].zone_verification`으로 오기 전에는 `verification.basis`가 `predefined_side_and_top_target_zones`가 될 수 없어 Fleet이 릴리스를 거부한다. 이 거부는 의도한 것이며, 가짜 `PASS`로 메우지 않는다.

#### 3. 신뢰 경계

owner-evidence는 셀의 owner로 등록된 서비스 주체만 보낼 수 있다. 다만 Fleet은 그 주체의 토큰이 정말 팔 owner 프로세스의 것인지 서명으로 확인하지 못한다. 막는 것은 lease 결속, claim 이후 시각, 완료 본문과의 일치, 재전송 불변이다. owner 서명은 후속 결정이다. 운영자 확인은 이름 있는 운영자만 낼 수 있고(공용 `site-console`·`development-*` 거부) 지도 ID와 함께 저장하며, 2 cm 넘는 이동이나 지도 변경이 한 번이라도 있으면 영구 무효다. 같은 요청의 재전송은 만료·자세를 갱신하지 않고, 새 확인은 이전 것이 무효가 된 뒤에만 받는다. 저장소는 메모리다. 재시작하면 확인·owner 증거가 사라져 거부로 돌아간다.

#### 4. 되돌리는 법

`amr_evidence_fn`과 `omx_evidence_fn` 연결(`site_map_routes.py`, `charge_bay_routes.py`)을 빼면 공급자 없음, 곧 전부 거부로 돌아간다.

### 한계

실물 인터록(기계식 브레이크, bed 센서, 명령 속도 출력)은 만들지 않았다. 위 값은 그것들의 대용 측정이며 실물·현장 수용을 대신하지 않는다.
