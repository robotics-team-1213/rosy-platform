---
module: isaac_sim
---
# Isaac 주행·관제·팔레타이징 연계 검토

작성: 2026-10-04. 조사 소스: main `f32643ffd`, 문서 목표 `d33034801`. 상태: 검토안. 기존 D-322/D-434와 D-446 목표를 연결하며 이번 회차에서 SDK·런너·주행 코드를 바꾸거나 원격 시뮬레이터를 실행하지 않는다.

## 권고

Gazebo의 고정 셀 수용과 별개로, **모델 PC의 Isaac에서 한 로봇의 CORE 주행을 확인한 뒤 Nav2와 두 로봇 Fleet 주행으로 확대**한다. 마지막에는 이동한 로봇이 정지·위치 확인을 마친 뒤 팔레타이징을 수행하는 흐름을 검토한다. 두 시뮬레이터가 같은 로봇의 실행·clock·센서를 동시에 소유하지 않는다.

Isaac 5.1 공식 문서는 ROS 2 Nav2 통합을 설명한다. 이는 연결 가능성의 근거이며 ROSY의 주행 수용을 증명하지 않는다. [NVIDIA ROS 2 Navigation](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/ros2_tutorials/tutorial_ros2_navigation.html).

## 현재 확인한 것

| 항목 | 현재 소스·기록 | 부족한 증거 |
|---|---|---|
| 형상·가져오기 | `learning/envs/isaac/prepare_urdf.py`, `model_checks.py`, OMX 형상 자산, D-397 기하 참조 | 모델 PC 실제 xacro 렌더, USD import·prim·관절·충돌 검사 |
| 주행 | `run_rosy.py`의 단일 로봇 Twist→바퀴 그래프, odom/joint state/TF/clock | 실제 직진·회전·멈춤 및 명령 유실 후 바퀴 정지 |
| 버전 | 현재 런너는 6.1 `URDFImporter` API, D-434는 모델 PC의 5.1 유지 | 실제 설치 버전 확인과 5.1 가져오기 호환 경로 |
| 센서·Nav2 | D-322에서는 첫 실행 이후 단계로 남아 있다. 현재 그래프는 기본 주행 중심 | scan·TF·clock·Nav2 lifecycle·목표 결과와 독립 실제 이동의 대응 |
| 두 로봇 | `graph_contract.py`는 namespace·frame 계약을 생성하나 런너는 단일 로봇 | 로봇별 ROS context/domain·prim·frame·목표 격리와 동일 장면의 관측 |
| Fleet | 기존 REST/WS·Task/attempt·CORE 경로와 D-426 수용 계획 | 실제 Isaac 로봇의 Fleet 등록·heartbeat·하달·상관 결과·교통/정지 수용 |
| 이동 후 적재 | Cell 코어·Fleet·OMX 고정 셀 경로 | 이동 후 셀 기준 좌표·위치 재확인, 운반/암 상태, 주행과 팔 실행의 상호 배제 |

기존 D-322의 바퀴 간격 기록과 현재 `graph_contract.py` 값은 다르다. 오래된 수치를 새 설정에 복사하지 않고 D-397 정본 기하와 런타임 회전 관측을 대조한다.

## 호스트와 권한

- **모델 PC:** Isaac·ROS 주행 스택·시뮬 CORE 두 인스턴스와 격리한 검증용 Fleet를 소유한다. 처음에는 headless·한 로봇·최소 센서로 시작한다. GPU 학습 작업과 자원 사용을 조정한다.
- **관제 PC:** 운영 Fleet·Vision·콘솔을 유지한다. 첫 Isaac 수용에서는 운영 로봇/DB/자격을 시뮬에 등록하거나 재사용하지 않는다. 운영 관제 Fleet의 직접 원격 제어 통합은 이후 별도 인증·transport·단절 검증 단계다.
- **작업 PC:** SSH·브라우저·원격 화면·증거 열람만 수행하며 로컬/WSL에서 시뮬레이터를 실행하지 않는다.
- **명령:** Fleet/화면은 CORE의 기존 외부 API만 사용한다. Nav2의 `cmd_vel_nav`/`nav_cmd_vel` 연결은 기존 navigation launch와 CORE 구독을 재사용하고, Isaac의 최종 `cmd_vel` 구독에 Nav2나 앱이 직접 별도 publisher로 붙지 않는다.
- **격리:** 별도 run ID·DB·토큰·포트·로봇 identity·ROS context/namespace·출력 경로를 둔다. 실제 로봇 domain과 겹치지 않는 검증 배치를 설계하되 D-4/D-33 identity 규칙을 임의 변경하지 않는다.

## 단계별 목표

| 단계 | 구현·확인 | 완료 조건 |
|---|---|---|
| I0 원격 기준선 | 모델 PC 신원·접속, 설치 버전·RAM·VRAM·ROS Bridge, 후보 SHA·SDK 환경 확인. 공식 문서 버전과 실제 API 대조 | 읽기 전용 점검 결과와 실행 자원·격리 설정 확보. D-434의 과거 RAM·설치 기록을 현재 사실로 단정하지 않음 |
| I1 한 대 주행 | 5.1 호환 import와 한 로봇 그래프. command freshness/독립 바퀴 정지, pause/reset/disconnect 대응 | 직진·회전·zero와 명령 중단 뒤 실제 정지, CORE 최종 publisher 하나, prim/관절/odom/TF/clock 일치 |
| I2 Nav2 | 센서/scan, 지도·위치 추정, use_sim_time·TF·lifecycle, 기존 CORE navigation 경로 | 관제 목표→CORE→Nav2→CORE 최종 명령→Isaac 이동·도착을 동일 Task/attempt와 독립 pose로 확인. 장애물·취소·stale sensor·clock reset도 검증 |
| I3 두 대 Fleet | 두 로봇 context/domain 격리, 실행별 scene/clock 소유, 실제 Fleet WS·REST·Task 결과 | 잘못된 로봇이 움직이지 않음, 공유 구간·점유·정지·재시작·통신 유실 수용. D-426의 수치·독립 관측 원칙을 Isaac에 대응시켜 판정 |
| I4 이동 후 적재 | 주행 완료·정지 관측 이후 셀 기준 좌표 재확인, 정식 Cell 제안·승인·실행 연결 | 주행과 암 동작 상호 배제, 불확실한 위치/적재물 상태에서 HOLD, 재시작 후 자동 재개 없음, 이동 및 최종 박스 위치를 각각 확인 |

I4는 고정 셀 G2를 자동으로 확장하지 않는다. 티칭한 Cell 해시가 이동 후에도 유효한지, base/world 좌표 변환의 책임과 신선도, 팔 탑재 형상·payload·운반 상태는 별도 설계가 필요하다. 움직이는 베이스에 기존 고정 셀 포즈를 그대로 적용하지 않는다.

## 공통 시험과 증거

물리 이동·도착 판정은 simulation time, 네트워크·명령 유효기간은 monotonic time으로 구분한다. pause/reset 이후 새 epoch를 두고 과거 명령·관측·완료를 이어 붙이지 않는다. ROS 2 Clock 문서는 sim-time 연결의 근거다. [NVIDIA ROS 2 Clock](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/ros2_tutorials/tutorial_ros2_clock.html).

SDK 성공 이벤트와 별개로 Isaac stage의 pose·contact·바퀴 상태를 검증용 독립 관측기가 읽는다. ground truth를 운영 위치 추정 입력으로 조용히 주입하지 않는다. D-426의 위치/방향/정지/footprint 간격/contact/관측 공백 기준을 시뮬레이터별 지원과 측정 결과에 맞춰 명시하고, 빠진 항목은 NOT_RUN/INCONCLUSIVE로 남긴다.

후보 SHA·로봇 모델/scene/map hash·SDK/Bridge 버전·run/epoch·Task/attempt·publisher GID·원본 관측·오차·정지 지연·장애 입력·판정 결과를 함께 보관한다. 학습 정책은 Nav2/CORE의 정상 경로를 입증한 이후 별도 승격 대상으로 둔다.

## 대안과 우선순위

1. **설치 기록의 5.1에 호환 경로를 추가:** D-434를 지키고 큰 재설치 전에 최소 동작을 확인할 수 있다. 다만 공식 5.1 문서는 현재 미지원 릴리스로 표시되므로 I0에서 실제 버전과 필요한 API·지원 제약을 재확인한다. 자동 업그레이드는 하지 않는다.
2. **지원 중인 새 버전으로 전환:** 가져오기 API와 지원 상태를 맞출 여지가 있지만 자원·설치·기존 scene/Bridge 회귀 비용이 있다. 모델 PC 조사 이후 별도 버전 결정을 한다.
3. **Gazebo 주행만 먼저:** 기존 실행 증거를 재사용하기 쉽지만 Isaac 목표를 충족하지 않는다. 고정 셀 Gazebo 흐름을 유지하면서 Isaac I0/I1부터 단계적으로 추가하는 안을 권고한다.

## 이번 회차 검증

`python -m pytest learning/envs/isaac/test -q`에서 **10 passed / 1 skipped**. skip은 sourced ROS 2 xacro overlay 부재로 실제 xacro 렌더 시험이 실행되지 않은 것이다. 이 결과는 그래프 계약·URDF/자산 helper의 host 검증이며 Isaac SDK 실행·모델 PC 접속·주행·Nav2·두 대 Fleet 수용은 아니다. runtime gate는 HOLD를 유지한다.

문서·네트워크·harness 계약 시험은 83 passed, 최종 lint는 0 errors/26 기존 warnings였다. 상대 링크·append-only log 형식·whitespace 검사를 통과했다.

## 완료 판정

전체 개발 완료는 D-446 G1–G3와 Isaac I0–I3의 증거가 모두 있어야 한다. 이동 후 적재까지 제품 범위로 정하면 I4도 필요하다. 현재는 **목표·검토 문서 작성 완료**, 앱·Gazebo·Isaac의 실제 종단 개발과 수용은 **미완료**다.
