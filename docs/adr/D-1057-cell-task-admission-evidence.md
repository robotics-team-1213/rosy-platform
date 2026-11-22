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
| `pose` | `MapPoseService.arbitrated_pose`. 활성 지도 ID가 있어야 하고, 그 지도·그래프에 셀 정차 지점이 실제로 있어야 한다(`resolve_omx_cells`의 기본 좌표로 만든 셀은 쓰지 않는다). LOCALIZED이고 앵커 출처가 sighting·pin·track·peer(`age_s` 2 s 이하)이며, odom으로 이은 `bridged`는 정지 불감대(`dead_reckon_m` ≤ 2 cm, `bridge_turn_deg` ≤ 2°) 안에서 같은 앵커가 신선할 때(`operator_pin` 10 s 이하, 그 밖 2 s 이하)만 수용하고 이동 중 추측 항법과 `auto_locate`는 거부한다. 활성 지도와 같은 `map_id`, 셀 정차 구역(사이트 지도 station 좌표에서 0.18 m 이내, `CELL_CLAIM_RADIUS_M`와 같은 값) 안일 때만 | None |
| `wheel_brake_locked` | CORE가 heartbeat로 보고하는 **정지 유지**: 모드 IDLE, navigation이 IDLE·ARRIVED·CANCELED·FAILED뿐(주행 진행 없음), 이 로봇의 Fleet 목표 없음, E-stop 아님, odom 선속·각속도가 임계(1e-4 m/s, 1e-3 rad/s) 이하. 표본마다 속도 채널 `received_at`이 heartbeat 도착 시각과 2 s 이내여야 하고, 이런 표본이 표본 간격 2.5 s 이하로 1 s 이상 이어져야 한다. **기계식 브레이크가 아니다.** 브레이크 센서는 없다 | heartbeat가 없거나 2 s보다 오래되면 None. 표본이 부족하면 False |
| `v_cmd_mps` | **명령 속도 원천 없음.** CORE는 명령 속도를 Fleet에 내놓지 않는다. 그래서 odom 선속(`StateSnapshot.velocity.linear`)과 CORE 모드로 대체한다. 값은 odom 0(정지)이며 명령값이 아니다. 명령은 냈지만 바퀴가 아직 움직이지 않은 순간은 속도로 가려낼 수 없으므로, 모드 IDLE이고 주행 진행(navigation)과 Fleet 목표가 없는 표본만 인정해 배제한다. 사용자 결정 (가)의 "정지 상태(속도 0)" 범위이며, 조정 세션이 이 대체를 확인했다 | 채널이 fresh가 아니면 None |
| `bed_ready` | 셀 S: 상단 카메라 판정(2-9절), UNKNOWN이면 이름 있는 운영자 확인. 셀 A/B: 이름 있는 운영자 확인. 운영자 확인(`POST .../bed-confirm`)은 유효 120 s, 확인 뒤 자세가 2 cm 넘게 움직이면 무효. bed 센서는 없다 | 확인 없음·만료·이동은 False |
| `observed_at` | 쓴 실시간 관측 중 가장 오래된 시각(heartbeat 도착, 속도 채널 수신, 지도 자세 관측). 운영자 확인은 자기 만료가 있어 실시간 관측에 넣지 않는다 | 하나라도 없으면 None |

판정 문턱 숫자(1 s, 2.5 s, 1e-3 rad/s, 120 s, 2 cm)는 이 ADR이 정한 값이다. 정지 표본은 0.5 s마다 heartbeat를 읽는 스레드가 쌓는다. 요청 때만 읽으면 claim과 완료 사이의 움직임을 놓친다.

#### 2. OMX owner 증거

Fleet은 `POST /api/fleet/pipeline/cell-tasks/{task_id}/owner-evidence`(proposer 권한)로 `receipt`, `stage_result`, `hardware_telemetry`를 먼저 저장한다. 그 셀의 owner로 등록된 서비스 주체만 보낼 수 있다(사이트 설정 `ROSY_FLEET_CELL_OWNERS=cell_s=id1,id2;cell_ab=id3`, 설정이 없으면 403 `OWNER_PRINCIPAL_NOT_REGISTERED`). 완료 요청도 저장 기록을 등록한 주체와 같아야 한다. RUNNING 작업이고 본문 `handoff_lease_id`가 원장 lease와 같고 `measured_at`이 claim 이후 60 s 이내이며 `hardware_telemetry.measured_at`과 2 s 안에서 같아야 한다. 본문은 64 KB까지다. 작업이 COMPLETED·CANCELLED·ABORTED가 되거나 기록이 만료되면 저장소에서 지운다. `omx_evidence_fn`은 이 저장 기록만 돌려준다. 완료 요청 본문을 복사해 돌려주지 않는다. 저장한 시각이 아니라 측정 시각(`measured_at`)을 기준으로 현재보다 60 s 넘게 지난 기록은 등록도 사용도 하지 않는다. 같은 lease에 같은 증거를 다시 보내면 한 건이고, 다른 증거는 409다.

셀 쪽은 `cell_auto_pick`의 `attempts[].verify`(새 상부 프레임 확인)를 `verification.placement`에 싣고, `folded`는 마지막 이동 단계가 settled 상태의 `park`이고 관절 readback이 설정 `plan.home`에서 3.0 이내(`chunk_runner_guards.SETTLE_TOL`와 같은 값)일 때만 참으로 한다. 측정이 없으면 `False`이고 Fleet이 `UNVERIFIED_CELL_COMPLETION`으로 거부한다.

**배치 측정의 결속:** `zone_verification`은 목적지 사이트의 `layer`·`col`·`row`가 설정에 있고 범위(0-2, 1-3, 1-2) 안일 때만 측정하며, 측정한 사이트·층이 작업의 `dst_site`·handoff tier와 같아야 실행기가 수용한다. 놓기 전 상부·측면 프레임과 놓은 뒤 촬영된 상부·측면 프레임이 모두 있어야 하고, 두 프레임은 같은 판정 시각에 2 s 이내여야 한다. 상부 구역을 측정하지 못하면 verified가 아니다.

**팔레트 높이 판정(셀 A/B):** 깊이는 셀에 이미 있는 D435 Z16 캡처(`cell_depth.capture_top_depth_z16_receipt`)를 배치 뒤 한 장 받아(5 s 한계, 노출 시각이 배치 뒤여야 함) 판정에 넘긴다. 다만 `cell_z_profile`의 현재 프레임 보정 검사는 독립 측면 Z 기준이 없어 항상 통과하지 못하므로 `z_gate`는 UNKNOWN이고 팔레트 완료는 아직 거부된다. 이 검사는 안전 판단이라 바꾸지 않았다. 검사 구역은 목표 칸에 고정한다(공용 `verify_stack_outcome`의 `strict_target`: 대체 구역·출발 칸 기본값·상부 증가만으로 target_present를 만드는 분기 차단).

#### 2-2. 셀 A/B의 독립 Z 기준은 D435 깊이의 상대 높이 (사용자 결정, 2026-11-20)

팔레트 높이 판정(`cell_z_profile`의 현재 프레임 보정 검사)은 독립 측면 Z 기준이 없어 어떤 영상에서도 ok가 되지 않았다. 실제 셀 프레임(2026-11-20, 읽기 전용 촬영 3세트)에서 확인한 사실은 다음과 같다.

| 항목 | 실측 | 이 결정에서의 값 |
|---|---|---|
| 테이블 평면 기준 절대 높이 | 프레임마다 평면 적합이 607.3–614.0 mm로 약 7 mm 흔들림(윗면 35.6–43.6 mm로 퍼짐) | 쓰지 않는다 |
| 컨테이너 윗면 − 인접 팔레트 바닥(같은 깊이 영상, 바닥 평면 적합) | 점유 칸 9곳 중앙값 24.0–33.5 mm(기대 30 mm), 빈 칸 −5.6…+4.9 mm, 바닥 평면 잔차 3.3–3.9 mm | 층 높이 ± 7 mm(`TOL_MM`), 바닥 평면 잔차 6 mm 이하 |
| 유효 깊이 비율 | 슬롯·바닥 0.88–0.99 | 0.80 이상(기존 게이트와 같음) |
| RGB-깊이 정렬 오차 | 5.6–5.9 px (이전 기록 4.89 px) | 상대 높이는 깊이 좌표에서 재므로 정렬은 구역 대응에만 쓴다. 허용 8 px, ROI를 6 px 줄인다 |

허용 오차는 요청의 ±5 mm 대신 ±7 mm다. 점유 칸 9곳 가운데 2곳(24.0 mm)이 ±5 mm를 벗어났고, 최대값 33.5 mm와 빈 칸 최대 4.9 mm 사이가 충분히 벌어져 있어 층 1·2의 구분(30 / 62.4 / 94.8 mm)에는 영향이 없다.

동작: 셀 설정 `zone_rois.floor`(팔레트 바닥 ROI 목록)와 `floor_depth_mm`(보정 때 기록한 각 바닥 패치의 깊이)가 있고 깊이 프레임이 있을 때만 `cell_depth_slots.depth_reference`가 슬롯의 점유와 층을 정한다. 바닥 패치마다 따로 유효 깊이 0.80 이상, 평면 잔차 6 mm 이하, 중앙값이 기록한 깊이 ±4 mm 이내(단일 프레임 잡음 0.8–1.5 mm, 5장 중앙값 0.3–0.5 mm에 대한 여유), 공통 평면이 각 패치에서 기록한 바닥(보정 평면)과 4 mm 넘게 다르지 않아야 하고(가려지거나 다른 평평한 면이 덮이거나 모든 패치가 같은 방향으로 4 mm 넘게 오염되면 거부), ROI는 깊이 좌표에서 정렬 오차(올림)+2 px 줄인다. 전체 정렬 오차가 8 px를 넘으면 거부하고, 목표 슬롯 ROI 안의 그림 엣지와 깊이 엣지 사이 국소 오차(깊이 픽셀 평균 거리)도 8 px를 넘으면 거부한다(실측: 좋은 슬롯 1.9–5.1 px, 자세 2의 오른쪽 슬롯은 11–12 px로 거부). 같은 카메라로 몇 초 간격의 두 촬영에서 바닥 패치 깊이가 최대 9 mm 달랐으므로 `floor_depth_mm`은 쓰는 자세에서 다시 기록해야 한다. 목표 슬롯의 셀별 `top` ROI가 없으면 공용 표로 되돌아가지 않고 미검증이다. 깊이 캡처와 구역 측정은 Fleet 작업(`--task-id`)에서 `floor` 설정이 있을 때만 하고, 읽기마다 3 s 마감을 다시 확인한다.

**깊이 다중 프레임 중앙값(측정 개선만, 판정 범위 불변):** 배치 뒤 깊이는 한 장이 아니라 `depth_frames`장(기본 5, 설정 1–9)을 한 V4L2 스트림에서 연속 캡처(15 fps, 워밍업 12장 포함 3 s 하드 마감, 실측 1.26 s)해 픽셀별 중앙값으로 줄인다. 유효 픽셀은 N장 중 과반이 유효한 픽셀뿐이다. 1이면 기존 단일 프레임 캡처를 쓴다. 버스트의 유지한 프레임마다 단일 프레임 캡처와 같은 검사를 한다(`ts-monotonic, ts-src-soe` 표시, 버퍼 바이트 수 정확, 이 캡처에서 나온 스탬프)에 더해 순번·스탬프가 연속이어야 하고 벽시계-단조 시계 오프셋이 0.5 s 넘게 움직이면 거부한다. 형식 표기 재시도를 포함한 전체에 3 s 마감 하나를 적용하고, 첫 유지 프레임이 배치 이후이며 공통 판정 시각에서 2 s 안이어야 한다. RGB 읽기(상단·측면)도 마감 하나를 공유하고 소켓은 남은 시간만 받는다. Fleet 작업이 아닌 실행은 동작 전 측면 촬영도 하지 않는다. 실제 셀에서 같은 장면을 5회 x 5프레임(25장) 읽기 전용으로 촬영해 슬롯 상대 높이(mm)의 표준편차를 비교했다(같은 ROI·정렬·바닥 기록값 사용):

| 슬롯 | 단일 프레임 평균 ± 표준편차 (n=24) | 5장 중앙값 표준편차 (무작위 5장 60회) | 5장 중앙값 표준편차 (촬영 묶음 5개) |
|---|---|---|---|
| c1r2 (점유) | 33.7 ± 1.48 | 0.51 | 0.52 |
| c2r2 (점유) | 31.0 ± 0.86 | 0.32 | 0.64 |
| c3r2 (점유) | 31.5 ± 1.12 | 0.52 | 0.74 |
| c1r1 (빈 칸) | 1.7 ± 1.20 | 0.51 | 0.16 |
| c2r1 (빈 칸) | 1.8 ± 0.92 | 0.32 | 0.72 |
| c3r1 (빈 칸) | 1.8 ± 0.79 | 0.31 | 0.23 |

프레임 잡음의 표준편차가 0.8–1.5 mm에서 0.3–0.5 mm로 약 1/2.5–1/3로 준다(촬영 묶음은 표본이 5개뿐이라 흔들림이 크다). 바닥 평면 잔차는 단일 1.27 mm에서 1.05 mm, 유효 픽셀 비율은 0.896에서 0.897로 같다. 중앙값은 프레임 잡음만 줄인다: 촬영마다 달라지는 ROI 정렬 오차(6.3 px)와 바닥 평면 적합의 체계적 차이(앞선 3세트에서 24.0–33.5 mm)는 줄지 않으며, 이 5개 묶음의 평균(31–34 mm)과 앞선 세트의 평균(26.5–29.9 mm)이 다른 것도 그 때문이다. 허용 오차와 안착 대역은 바꾸지 않았다.

**역할 분리:** 깊이는 **층(Z) 식별**만 한다(점유이고 중앙값이 기대 높이 ±7 mm). 지정 구역에서 배치가 일어났다는 증거는 별도로 요구한다: (1) 놓기 전후 상부 영상이 목표 칸에서 **전역 밝기·대비를 뺀 뒤** 바뀌어야 하고(조명만 바뀐 경우는 바뀐 것이 아니다) 동시에 (2) 배치 후 깊이가 목표 칸을 층 높이의 절반 이상 솟은 픽셀 비율 0.5 이상으로 보여야 한다(둘 다 필요). 방향은 배치 후 깊이에서 솟은 덩어리(층 높이 절반 이상 픽셀)의 주축으로 판정한다(길이 비 1.5 이상, 화면 세로에서 25° 이내). 같은 프레임을 전후로 넣으면 거부된다. 안착·높이 이상 판정은 기존 대역을 그대로 쓴다: 같은 잔차(깊이 상대 높이 − 기대 높이)에 `evaluate_signed_tier_residual_mm`(−4…+1 mm PASS, 1–3 mm `S6_UNSEATED_CONE`, ≤ −4 mm `S2`, 그 밖 `S5`)와 `post_release` 게이트를 바꾸지 않는다. ±7 mm의 근거(점유 9곳 24.0–33.5 mm, 빈 칸 −5.6…+4.9 mm)는 1층을 빈 칸과 구분하는 데만 쓰며 2·3층이나 안착 허용 범위의 근거가 아니다. 깊이 잡음(3–4 mm)이 이 대역과 비슷해 실제 프레임에서는 일부 슬롯만 PASS 한다.

**알려진 한계:** 안착 대역(−4…+1 mm)은 깊이 잡음(약 3–4 mm)과 비슷하다. 대역은 바꾸지 않았으므로 깊이 기준은 층 식별과 점유를 증명하고, 안착 PASS는 측정이 대역 안에 들어온 슬롯에서만 나온다. 놓기 전 목적지 점유는 `pre_motion_frame`의 상부 지도 검사가 막는다.

**알려진 공백:** `cell_auto_pick`은 측면·상부 구역 측정(`cell_area_zones`)을 내놓지 않는다. 그 결과가 `attempts[].zone_verification`으로 오기 전에는 `verification.basis`가 `predefined_side_and_top_target_zones`가 될 수 없어 Fleet이 릴리스를 거부한다. 이 거부는 의도한 것이며, 가짜 `PASS`로 메우지 않는다.

#### 2-1. 셀 S는 상단 카메라 판정만으로 RELEASED (사용자 결정, 2026-11-20)

셀 S에는 측면 카메라가 없다. 그래서 `cell_id == "cell_s"`일 때만 Fleet 완료 검사와 worker, `cell_task_exec`가 `verification.basis == "top_camera_only_target_zone"`을 받아들인다. 셀 A/B는 지금처럼 `predefined_side_and_top_target_zones`가 필수이고 상단 전용 기준은 `UNVERIFIED_CELL_COMPLETION`으로 거부한다. 셀 S 상단 판정도 놓기 전 프레임과 놓은 뒤 프레임을 모두 요구하고, 사이트의 `auto_roi`(지정 구역)에서 구역이 채워졌고(채움 비율이 0.15 이상 늘어남) 두 프레임이 배치 뒤 촬영·2 s 이내일 때만 verified다. 측정한 사이트·구역은 작업의 `dst_site`·tier와 같아야 한다. 가드의 다른 조건(접힘, lease, 시각)은 그대로다.

#### 2-3. 셀 A/B claim 게이트 (깊이 판정 수용 전까지 꺼 둠)

셀 A/B의 배치·높이 증거(2-2절)는 실제 현장 수용 전이다. 그래서 Fleet `claim`은 `cell_ab` 작업을 `ROSY_FLEET_CELL_AB_RELEASE_ENABLED`(기본 꺼짐, `1`·`true`·`yes`·`on`만 켬, 호출 때 읽음)가 켜져 있지 않으면 `claimed:false`, `reason: CELL_AB_EVIDENCE_NOT_ENABLED`로 거부한다. 거부는 `_ready_amr` 앞이고 원장에서 무엇도 바꾸기 전이라 작업 상태·`handoff_lease_id`·셀 상태가 그대로다(팔이 움직인 뒤 완료가 거부되는 일을 막는다). 셀 S는 영향이 없다. 깊이 판정이 수용되면 사이트 설정에서 켠다. 되돌리는 법은 설정을 끄는 것이다.

#### 2-4. claim 때 owner 확인과 결과 재전송

`claim`은 호출 주체가 그 셀의 owner로 등록(`ROSY_FLEET_CELL_OWNERS`)되어 있지 않으면 원장을 바꾸기 전에 `claimed:false`, `OWNER_PRINCIPAL_NOT_REGISTERED`로 거부한다(등록되지 않은 주체가 claim하면 결과를 받아 줄 수 없어 작업이 RUNNING으로 남기 때문이다. 인증이 없는 단독 시험 앱은 확인하지 않는다). 팔 실행 뒤 `owner-evidence` 또는 `/complete` 전송이 실패하면 worker가 같은 lease의 결과를 작업 공간 상태 파일(`pending-results.json`)에 보관하고, 다음 폴링마다 **팔을 다시 움직이지 않고** 같은 본문을 재전송한다. 재전송은 Fleet이 그 작업을 RUNNING으로 보이고 lease가 같을 때만 한다(lease가 바뀌었거나 작업이 끝났으면 항목을 버린다). 같은 `owner-evidence` 본문은 Fleet이 동일 기록으로 받고 다른 본문은 409를 유지한다(2-7절: 원래 증거가 유효한 동안은 그 409를 "이미 기록됨"으로 보고 `/complete`만 다시 보낸다). 그 밖의 409·422는 다시 시도하지 않는다(적재함 확인 무효는 2-7절). 403·5xx·연결 끊김은 다음 폴링에 다시 시도한다.

#### 2-5. 감독 시험은 사람이 표시한 작업만, 나머지는 D-911 검토 범위 (사용자 결정, 2026-11-20)

worker는 `--commissioning --person-at-switch`를 더 이상 항상 넘기지 않는다(사람이 전원 스위치 옆에 있다는 선언을 소프트웨어가 대신하지 않는다, D-911 4). 이름 있는 운영자가 `POST .../presence-confirm`으로 작업에 입회 표시를 하고(120 s), 그 작업의 `claim`이 표시를 소비해 `handoff.presence`로 실을 때만 worker가 그 작업을 감독 시험으로 실행한다. 표시가 없거나 만료·익명이면 `cell_envelope`의 검토된 운전 범위(D-911 `reviews`, `task_sha256` 일치)로만 실행한다. 검토 기록이 없으면 러너가 **팔을 움직이기 전에** `held: not_reviewed`로 멈추고, worker는 `phase: ABORTED`, 사유 `REVIEW_REQUIRED`로 보고한다(claim 전에 Fleet이 envelope 검토 여부를 알지 못하므로 claim 후·동작 전에 판정한다; 팔은 움직이지 않고 owner 증거도 보내지 않는다). ABORTED는 기존대로 AMR 이동 억제를 유지하고 사람이 푼다. 이름 있는 운영자가 팔 접힘을 확인한 뒤 `POST /api/fleet/pipeline/arm-holds/clear`를 호출하면 남아 있는 팔 hold·사람 감지·`RUNNING`/`PAUSED_HUMAN` 작업이 없을 때만 해당 셀의 `ABORTED` 인터락을 `IDLE`(`amr_motion_inhibited=False`)로 해제하고 원장을 저장한다.

**시운전 뒤 D-911 검토 기록:** 자동 등록은 D-911 3·7이 허용하지 않는다(성공이 스스로 승격하지 않고 반복 수·성공률·시작 오차 기준은 검토자가 정하며 기본값이 없다). 대신 기존 절차를 한 단계로 만든 `deploy/robot/omx/cell_envelope_review.py`가 있다: 시험 뒤 `list <work-dir>/attempts.jsonl`로 후보(작업 key·시험 수·성공 수)를 보고, 사람이 `add --attempts ... --envelope ... --task-sha256 ... --reviewed-by ... --evidence-ref ... --min-attempts N --min-success-rate R --home-tolerance U --confirm-physical-review`를 실행한다. 작업 key·scope·`attempts_sha256`은 장부에서 복사하고 검토자·근거·세 숫자는 사람이 준다(기본값 없음). 시험이 그 숫자를 못 채우거나 hardware가 아니거나 이미 검토가 있으면 기록하지 않는다. 규칙은 바뀌지 않았다.

#### 2-6. 오래된 보관 결과는 팔을 움직이지 않고 다시 측정해 보낸다 (사용자 결정, 2026-11-20)

worker가 보관한 결과(2-4절)의 `owner-evidence`가 `measured_at` 기준 65 s 이상 지났으면(Fleet 한계 60 s + 두 시계 여유; 2-7절) 재전송 전에 **팔 없이** 다시 측정한다: 보관해 둔 놓기 전 프레임(작업 공간의 `zone-before`)과 새 상부(·측면) 프레임으로 배치 판정을 다시 하고(셀 S는 상단 전용), 접힘은 지금의 러너 상태와 보관한 `park` readback이 모두 접힘이어야 하며, 새 `measured_at`·digest의 `owner-evidence`와 `/complete` 본문으로 보관 결과를 바꿔 보낸다(재측정에 필요한 맥락은 prep 폴더의 `remeasure-<task_id>.json`에 두고 Fleet에는 보내지 않는다). 다시 측정이 실패하면(프레임 없음, 판정 불합격, 접힘 아님 등) 사유를 보관 항목의 `last_refusal`에 남기고 아무것도 보내지 않으며 작업은 RUNNING으로 남아 사람이 정리한다. lease가 바뀌었거나 RUNNING이 아니면 재측정도 재전송도 하지 않는다.

#### 2-7. 검토 7차: 입회는 이번 실행의 것만, 검토된 작업은 검토 경로, 재전송은 원래 증거부터, 적재함 확인은 lease에 묶는다

1. **저장된 설정은 입회를 대신하지 못한다.** `cell_auto_setup.open_cell`은 설정 JSON의 `_commissioning`을 지우고(경고를 stderr에 남긴다) 이번 실행의 `--commissioning --person-at-switch`(Fleet 입회 확인이 있을 때만 worker가 넘긴다)로만 가드에 전달한다.
2. **검토가 끝난 작업이 먼저다.** `cell_envelope.assess`는 `operating_envelope_path`에 이 `task_sha256`의 검토가 있으면 `_commissioning`이 와도 검토 경로(자동 운전 검사)를 탄다. 시운전 분기는 검토 기록이 없을 때만이다. 그래서 입회 표시가 다시 들어와도 시운전 행이 쌓여 `attempts_sha256`이 달라지는 일(`evidence_changed`)이 없다.
3. **재전송은 원래 증거부터.** Fleet이 원래 owner 증거를 60 s 들고 있는 동안은 같은 본문으로 `/complete`만 다시 보낸다. `owner-evidence`의 409 `OWNER_EVIDENCE_ALREADY_RECORDED`는 이미 기록됨으로 보고 항목을 지우지 않고 `/complete`를 이어 보낸다(다른 409는 그대로 버린다). 팔 없는 재측정은 원래 증거가 만료된 뒤(`STALE_S` = 65 s)에만 한다. 그 사이 `/complete`가 422 `OMX_OWNER_EVIDENCE_UNAVAILABLE`이면 항목을 두고 다음 폴링에 다시 한다.
4. **적재함 확인은 claim에서 소비해 lease에 묶는다.** `claim`이 유효한 적재함 확인을 쓰고 확인자·`confirmed_at`·그때의 자세·지도 ID·버전을 작업 행 `bed_confirmation`과 lease에 묶는다. 묶인 뒤 `RELEASED`는 120 s 만료를 다시 보지 않는다(120 s는 claim까지의 대기만 잰다). 다시 확인하는 것은 "확인 뒤 2 cm 넘는 이동 없음·지도 변경 없음"(기존 영구 무효 규칙, 상태 갱신마다)과 정지·정지 위치 증거(`amr_evidence`, 변경 없음)다. 확인이 무효가 됐으면 `/complete`는 422 `BED_CONFIRMATION_INVALID`(속도·정지 미측정은 기존 `AMR_BRAKE_BED_VELOCITY_UNMEASURED`)를 돌려준다. 이때 이름 있는 운영자가 RUNNING 작업에 `bed-confirm`을 다시 보낼 수 있다(같은 lease, 로봇이 지금 정지·정지 구역이어야 하며 아니면 409 `BED_CONFIRM_ROBOT_NOT_STOPPED`; 유효한 확인이 있으면 여전히 409 `CELL_TASK_NOT_QUEUED`). worker는 이 422에서 보관 결과를 두고 `last_refusal`에 사유를 남긴 채 사람을 기다리고, 다른 422(불일치 등)는 이전처럼 버린다.

#### 2-8. 검토 8차: 60초 경계의 응답은 보관·재측정, claim은 결속과 한 단계

- 재전송 응답 정리(보관 결과는 `pending-results.json`): 증거 나이가 60 s 이상 65 s 미만이면 아무것도 보내지 않고 보관(Fleet이 거부할 것이므로), 65 s 이상이면 팔 없는 재측정 뒤 전송. 422 `OWNER_EVIDENCE_MEASURED_AT_INVALID`·`OMX_OWNER_EVIDENCE_UNAVAILABLE`(만료 계열)은 삭제하지 않고 `last_refusal`과 함께 보관해 다음 재측정 시점에 다시 한다. 422 `BED_CONFIRMATION_INVALID`는 사람 대기(보관). 연결 끊김·403·5xx·원래 증거 409 `OWNER_EVIDENCE_ALREADY_RECORDED`는 보관·계속. 그 밖의 409·422(본문 불일치, 작업이 RUNNING 아님 등)와 lease가 바뀐 작업만 삭제한다.
- `claim`은 적재함 확인의 lease 결속(`bind_bed`, 한 번 잡은 `now`로 120 s 판정)을 원장 변경(셀 상태·`RUNNING`·lease) 앞에서 하고, 확인이 그사이 만료되었으면 `claimed:false`, `AMR_BRAKE_BED_VELOCITY_UNMEASURED`로 거부한다(작업은 QUEUED). 119.9 s는 통과, 120.1 s는 거부.
- **정지 자세 `bridged`·outbox 보류:** `MapPoseTracker`가 1 Hz odom 갱신·보간에서 반환하는 정지 `bridged` 자세(`dead_reckon_m` ≤ 2 cm, `bridge_turn_deg` ≤ 2°, `sighting`/`track`/`peer` 2 s 이하 또는 `operator_pin` 10 s 이하)만 `zone_pose()`가 수용한다. 이동 중 dead-reckoning은 계속 거부되며, `cell_result_outbox`는 `/complete`의 `422 AMR_BRAKE_BED_VELOCITY_UNMEASURED`를 버리지 않고 보관해 재측정·재전송한다.

#### 2-9. 셀 S의 적재함 준비는 상단 카메라가 판정한다 (사용자 결정, 2026-11-21)

셀 S 완전 자동화(D-1047·D-1048)에 따라 셀 S의 `bed_ready`는 운반마다 운영자가 확인하지 않고 셀 S 상단 카메라가 판정한다. 가드(`_ready_amr`, `complete_cell_task`)와 lease 결속·무효화 규칙(2-7절 4, 3절)은 바꾸지 않는다. 카메라 판정은 운영자 확인과 같은 기록을 만들고, 다른 점은 출처(`source: cell_top_camera`)와 claim까지의 유효 시간(10 s)이다.

- **판정(셀 호스트 worker, claim 직전):** 상단 프레임 3장(`source_seq` 증가, 1.0 s 이상 간격, 각 2 s 이내), 카메라 보정 미이동, 팔 접힘(60 s 이내), 등록한 도킹 기준 프레임과 적재함 테두리 일치(상관 문턱 이상, 이동 2 cm 이하), 3장 사이 정지, 하역 작업이면 목록 일치 물체 1개 이상이 모두 적재함 다각형 안. 모두 참이면 READY, 측정한 부정은 NOT_READY, 측정 못하면 UNKNOWN이다. ROI는 셀 설정의 `sites.pinky`만 쓰고 코드 기본값은 쓰지 않는다. 기준 프레임이 없으면 늘 UNKNOWN이다.
- **기록(Fleet):** `POST .../bed-observation`은 셀 S owner 서비스 주체만, QUEUED 작업에만 받는다. READY일 때 Fleet은 자기 측정으로 다시 묶는다: 지도 자세가 정차 구역 안이고(1절 `pose`), 정지 유지(1절 `wheel_brake_locked`)가 카메라 첫 프레임보다 앞서 시작했어야 한다(두 호스트 시계 여유 0.5 s). 확인자·시각·자세·지도 ID·버전을 저장하고 claim이 lease에 묶는다.
- **UNKNOWN은 통과가 아니다.** UNKNOWN이면 기록을 만들지 않으며 claim은 `AMR_BRAKE_BED_VELOCITY_UNMEASURED`로 거부된다. 이때 이름 있는 운영자의 `bed-confirm`이 대체 경로다. 카메라가 10 s 이내에 NOT_READY라고 한 작업에는 운영자 확인을 받지 않는다(409 `BED_CAMERA_NOT_READY`).
- **RUNNING 재확인은 운영자만** 한다(집은 뒤에는 적재함 내용이 달라 카메라 조건이 성립하지 않는다).
- **셀 A/B**는 바뀌지 않는다: 카메라 기록을 받지 않고(409 `BED_CAMERA_CELL_NOT_SUPPORTED`) 운영자 확인만 쓴다.
- **끄는 법:** 사이트 설정 `ROSY_FLEET_CELL_S_BED_CAMERA=off`(Fleet, 호출 때 읽음) 또는 셀 설정에서 `sites.pinky.bed_reference` 제거. 둘 다 운영자 확인 경로로 돌아간다.

**한계:** 카메라 판정은 bed 센서가 아니다. 적재함 고정 상태(걸쇠)와 화물 무게는 보지 못한다. 기준 프레임과 문턱은 현장 도킹 3회 실측으로 정하며, 실물·현장 수용은 별도다.

#### 3. 신뢰 경계

owner-evidence는 셀의 owner로 등록된 서비스 주체만 보낼 수 있다. 다만 Fleet은 그 주체의 토큰이 정말 팔 owner 프로세스의 것인지 서명으로 확인하지 못한다. 막는 것은 lease 결속, claim 이후 시각, 완료 본문과의 일치, 재전송 불변이다. owner 서명은 후속 결정이다. 운영자 확인은 이름 있는 운영자만 낼 수 있고(공용 `site-console`·`development-*` 거부) 지도 ID와 함께 저장하며, 2 cm 넘는 이동이나 지도 변경(ID 또는 활성 버전)이 한 번이라도 있으면 영구 무효이고, 확인은 조회 때만이 아니라 콘솔이 받는 상태 갱신마다 검사한다. 같은 요청의 재전송은 만료·자세를 갱신하지 않고, 새 확인은 이전 것이 무효가 된 뒤에만 받는다. 카메라 판정 기록은 셀 S owner 서비스 주체만 낼 수 있고, Fleet은 그 판정을 자기 자세·정지 측정으로 다시 묶는다. 서비스 토큰이 정말 카메라 판정 프로세스의 것인지는 서명으로 확인하지 못한다(owner 증거와 같은 후속 과제). 저장소는 메모리다. 재시작하면 확인·owner 증거가 사라져 거부로 돌아간다.

#### 4. 되돌리는 법

`amr_evidence_fn`과 `omx_evidence_fn` 연결(`site_map_routes.py`, `charge_bay_routes.py`)을 빼면 공급자 없음, 곧 전부 거부로 돌아간다.

### 한계

실물 인터록(기계식 브레이크, bed 센서, 명령 속도 출력)은 만들지 않았다. 위 값은 그것들의 대용 측정이며 실물·현장 수용을 대신하지 않는다.
