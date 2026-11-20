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

동작: 셀 설정 `zone_rois.floor`(팔레트 바닥 ROI 목록)와 `floor_depth_mm`(보정 때 기록한 각 바닥 패치의 깊이)가 있고 깊이 프레임이 있을 때만 `cell_depth_slots.depth_reference`가 슬롯의 점유와 층을 정한다. 바닥 패치마다 따로 유효 깊이 0.80 이상, 평면 잔차 6 mm 이하, 중앙값이 기록한 깊이 ±15 mm 이내, 공통 평면과의 차 4 mm 이하여야 하고(가려지거나 다른 평평한 면이 덮이면 거부), ROI는 깊이 좌표에서 정렬 오차(올림)+2 px 줄인다. 정렬 오차가 8 px를 넘으면 거부한다. 목표 슬롯의 셀별 `top` ROI가 없으면 공용 표로 되돌아가지 않고 미검증이다. 깊이 캡처와 구역 측정은 Fleet 작업(`--task-id`)에서 `floor` 설정이 있을 때만 하고, 읽기마다 3 s 마감을 다시 확인한다.

**깊이 다중 프레임 중앙값(측정 개선만, 판정 범위 불변):** 배치 뒤 깊이는 한 장이 아니라 `depth_frames`장(기본 5, 설정 1–9)을 한 V4L2 스트림에서 연속 캡처(15 fps, 워밍업 12장 포함 3 s 하드 마감, 실측 1.26 s)해 픽셀별 중앙값으로 줄인다. 유효 픽셀은 N장 중 과반이 유효한 픽셀뿐이다. 1이면 기존 단일 프레임 캡처를 쓴다. 실제 셀에서 같은 장면을 5회 x 5프레임(25장) 읽기 전용으로 촬영해 슬롯 상대 높이(mm)의 표준편차를 비교했다(같은 ROI·정렬·바닥 기록값 사용):

| 슬롯 | 단일 프레임 평균 ± 표준편차 (n=24) | 5장 중앙값 표준편차 (무작위 5장 60회) | 5장 중앙값 표준편차 (촬영 묶음 5개) |
|---|---|---|---|
| c1r2 (점유) | 33.7 ± 1.48 | 0.51 | 0.52 |
| c2r2 (점유) | 31.0 ± 0.86 | 0.32 | 0.64 |
| c3r2 (점유) | 31.5 ± 1.12 | 0.52 | 0.74 |
| c1r1 (빈 칸) | 1.7 ± 1.20 | 0.51 | 0.16 |
| c2r1 (빈 칸) | 1.8 ± 0.92 | 0.32 | 0.72 |
| c3r1 (빈 칸) | 1.8 ± 0.79 | 0.31 | 0.23 |

프레임 잡음의 표준편차가 0.8–1.5 mm에서 0.3–0.5 mm로 약 1/2.5–1/3로 준다(촬영 묶음은 표본이 5개뿐이라 흔들림이 크다). 바닥 평면 잔차는 단일 1.27 mm에서 1.05 mm, 유효 픽셀 비율은 0.896에서 0.897로 같다. 중앙값은 프레임 잡음만 줄인다: 촬영마다 달라지는 ROI 정렬 오차(6.3 px)와 바닥 평면 적합의 체계적 차이(앞선 3세트에서 24.0–33.5 mm)는 줄지 않으며, 이 5개 묶음의 평균(31–34 mm)과 앞선 세트의 평균(26.5–29.9 mm)이 다른 것도 그 때문이다. 허용 오차와 안착 대역은 바꾸지 않았다.

**역할 분리:** 깊이는 **층(Z) 식별**만 한다(점유이고 중앙값이 기대 높이 ±7 mm). 지정 구역에서 배치가 일어났다는 증거(놓기 전후 상부 영상이 목표 칸에서 바뀜, 바뀐 모양이 세로로 섬)는 깊이와 별도로 계속 요구한다. 같은 프레임을 전후로 넣으면 거부된다. 안착·높이 이상 판정은 기존 대역을 그대로 쓴다: 같은 잔차(깊이 상대 높이 − 기대 높이)에 `evaluate_signed_tier_residual_mm`(−4…+1 mm PASS, 1–3 mm `S6_UNSEATED_CONE`, ≤ −4 mm `S2`, 그 밖 `S5`)와 `post_release` 게이트를 바꾸지 않는다. ±7 mm의 근거(점유 9곳 24.0–33.5 mm, 빈 칸 −5.6…+4.9 mm)는 1층을 빈 칸과 구분하는 데만 쓰며 2·3층이나 안착 허용 범위의 근거가 아니다. 깊이 잡음(3–4 mm)이 이 대역과 비슷해 실제 프레임에서는 일부 슬롯만 PASS 한다.

**알려진 한계:** 안착 대역(−4…+1 mm)은 깊이 잡음(약 3–4 mm)과 비슷하다. 대역은 바꾸지 않았으므로 깊이 기준은 층 식별과 점유를 증명하고, 안착 PASS는 측정이 대역 안에 들어온 슬롯에서만 나온다. 놓기 전 목적지 점유는 `pre_motion_frame`의 상부 지도 검사가 막는다.

**알려진 공백:** `cell_auto_pick`은 측면·상부 구역 측정(`cell_area_zones`)을 내놓지 않는다. 그 결과가 `attempts[].zone_verification`으로 오기 전에는 `verification.basis`가 `predefined_side_and_top_target_zones`가 될 수 없어 Fleet이 릴리스를 거부한다. 이 거부는 의도한 것이며, 가짜 `PASS`로 메우지 않는다.

#### 2-1. 셀 S는 상단 카메라 판정만으로 RELEASED (사용자 결정, 2026-11-20)

셀 S에는 측면 카메라가 없다. 그래서 `cell_id == "cell_s"`일 때만 Fleet 완료 검사와 worker, `cell_task_exec`가 `verification.basis == "top_camera_only_target_zone"`을 받아들인다. 셀 A/B는 지금처럼 `predefined_side_and_top_target_zones`가 필수이고 상단 전용 기준은 `UNVERIFIED_CELL_COMPLETION`으로 거부한다. 셀 S 상단 판정도 놓기 전 프레임과 놓은 뒤 프레임을 모두 요구하고, 사이트의 `auto_roi`(지정 구역)에서 구역이 채워졌고(채움 비율이 0.15 이상 늘어남) 두 프레임이 배치 뒤 촬영·2 s 이내일 때만 verified다. 측정한 사이트·구역은 작업의 `dst_site`·tier와 같아야 한다. 가드의 다른 조건(접힘, lease, 시각)은 그대로다.

#### 3. 신뢰 경계

owner-evidence는 셀의 owner로 등록된 서비스 주체만 보낼 수 있다. 다만 Fleet은 그 주체의 토큰이 정말 팔 owner 프로세스의 것인지 서명으로 확인하지 못한다. 막는 것은 lease 결속, claim 이후 시각, 완료 본문과의 일치, 재전송 불변이다. owner 서명은 후속 결정이다. 운영자 확인은 이름 있는 운영자만 낼 수 있고(공용 `site-console`·`development-*` 거부) 지도 ID와 함께 저장하며, 2 cm 넘는 이동이나 지도 변경(ID 또는 활성 버전)이 한 번이라도 있으면 영구 무효이고, 확인은 조회 때만이 아니라 콘솔이 받는 상태 갱신마다 검사한다. 같은 요청의 재전송은 만료·자세를 갱신하지 않고, 새 확인은 이전 것이 무효가 된 뒤에만 받는다. 저장소는 메모리다. 재시작하면 확인·owner 증거가 사라져 거부로 돌아간다.

#### 4. 되돌리는 법

`amr_evidence_fn`과 `omx_evidence_fn` 연결(`site_map_routes.py`, `charge_bay_routes.py`)을 빼면 공급자 없음, 곧 전부 거부로 돌아간다.

### 한계

실물 인터록(기계식 브레이크, bed 센서, 명령 속도 출력)은 만들지 않았다. 위 값은 그것들의 대용 측정이며 실물·현장 수용을 대신하지 않는다.
