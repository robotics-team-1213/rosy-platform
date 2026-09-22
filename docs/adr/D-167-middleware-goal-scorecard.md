## D-167 미들웨어 목표는 평가표로 측정한다 — 8개 판정 축과 기준선

**Status:** Proposed (2026-09-22). 이 ADR은 "우리가 무엇을 하려는 미들웨어인가"를
판정 가능한 표로 고정한다. 첫 평가 회차가 이 표를 실측으로 채우면 Accepted로
뒤집는다(D-162와 같은 패턴).

**Context:** 미들웨어의 목표는 세 문서에 흩어져 있다 — CORE SRS §1.1(유일한 관문)·
§1.3(Local-First, 외부 cmd_vel 금지), D-63(얇은 CORE + 선택 슬라이스), D-59(사이트
계약 버스·역할 단일). 각각은 "결정"으로는 살아 있지만, **"지금 우리가 그 목표에
얼마나 갔는가"를 한 장에 앉혀 판정하는 표는 없다.** 모듈 게이트(D-61)는 모듈별 시험
건강을 재지 목표 자체를 재지 않는다 — core 스위트가 초록이어도 "safety가 벤더를
모르는가", "관제가 꺼져도 안전한가"라는 축은 아무 게이트도 직접 재지 않는다.
D-153이 화면에는 평가표(세 계층)를 만들어 놓았으나 목표 축에는 같은 장치가 없다.
그 결과 기준선도 적혀 있지 않아 "목표 달성/미달"을 논쟁으로만 말할 수 있었다.
이 ADR은 목표 진술, 판정 축, 측정 수단, 그리고 오늘(2026-09-22)의 기준선을 한 표로
고정한다.

**Decision:**

1. **목표 진술.** 우리가 하려는 미들웨어는 "로봇 1대가 중앙 서버 없이 안전하게
   독립 운용하고, 외부에는 ROS를 숨긴 API만 보이며, 그 안의 CORE는 얇아서 필수만
   갖고 선택 슬라이스는 따로 얹는다. 사이트(관제)는 계약 버스로만 모이고 흩어지며,
   관제가 죽어도 로봇은 안전하다"이다. 이 문장은 위 축 표(§3)로만 판정한다.

2. **판정 축은 여덟 개이고 총점은 없다.** 축마다 GO/HOLD/PARKED/N/A와 증거 계층
   (LOCAL/ROS-SIM/ARTIFACT/DEVICE/FIELD)을 붙인다(D-61 어휘 재사용, 새 어휘 없음).
   **8축 전부 GO여야 "미들웨어 목표 달성"이며, 하나라도 HOLD면 미달이다** —
   안전 항을 점수로 희석하지 않기 위해 합산 점수(0–100)를 쓰지 않는다.

3. **축 표 (이것이 평가표다).**

   | # | 축 (무엇을 하고 싶은가) | 판정 질문 (이게 아니면 HOLD) | 측정 수단 | 기준선 2026-09-22 | 판정 |
   |---|---|---|---|---|---|
   | G-1 | 단일 관문 | 외부 클라이언트가 ROS를 모르고 ROSY API로만 상태·명령·이벤트에 닿는가 | `test_v1_import_boundary.py`, `test_protocol_schemas.py`, API Ref | v1 라우터의 `core_features` 직접 import 금지 가동, 스키마 단일 원천(D-18) 유지 | GO (LOCAL) |
   | G-2 | Local-First 독립 운용 | Fleet 없이 로봇 1대가 부팅·상태·제어·정지에 닿는가 | compose core 단독 기동 + `GET /api/v1` health | `docs/validation/ros-sim-core-2026-09-22` PASS(부트 로그·api-health.json); 실기 Pi readback 없음 | GO (ROS-SIM) / DEVICE HOLD |
   | G-3 | 단일 최종 명령 | `/cmd_vel` 발행자가 Command Manager 하나뿐인가(외부·Fleet 포함) | `ros2 topic info` 발행자 수, `test_core_logic` 멀렉서 | `cmdvel-info.txt` **Publisher count: 1**, `/nav_cmd_vel`은 구독만 (2026-09-22 실측) | GO (ROS-SIM) / DEVICE 미측정 |
   | G-4 | 얇은 CORE | `rosy-core` 이미지·코드에 카메라·팔·추론·omx·control 슬라이스가 없는가 | Dockerfile core stage COPY 목록, `test_runtime_slices.py` FORBIDDEN, D-126 entry-point | core-build COPY는 `src/core/{interfaces,core}`만; `control` 정적 import 금지(어댑터 entry-point 1곳) | GO (SOURCE) / ARTIFACT HOLD |
   | G-5 | 선택 슬라이스 설치 | 없는 슬라이스는 설치에 없고 capability가 false인가 | `board.yaml` `required==["core"]`, `capabilities.*.yaml`, `install-pi.sh --slices` | `test_runtime_slices`: required `["core"]`, vision/omx/ai는 카탈로그 only (D-62) | GO (SOURCE) / DEVICE HOLD |
   | G-6 | 정책의 벤더 독립 | safety·command·navigation이 벤더·카메라·팔을 모른가 | 소스 스윕(omx/moveit/picamera/dynamixel), D-155 AST 가드 | D-155 가드 존재, **그러나 `core_features/safety/manager.py:318,326`에 `pinky_calmap227` 파티션 리터럴 잔존** — 벤더명이 안전 정책 코드에 침투한 흔적 | HOLD — sim 파티션 상수를 설정/프로파일로 옮길 때까지 |
   | G-7 | 사이트 계약 버스 | 디바이스 간 직접 ROS 없이 계약(envelope·REST·소켓)만 오가고 관제 역할이 단일한가 | `src/site/fleet/test`, D-59 역할 가드, `test_dds_identity_contracts` | fleet LOCAL GO(스위트 잔존), **ROS-SIM HOLD(D-87: 현재 트리의 colcon install/setup.bash 부재)**, Fleet 서버 v1 미완 | HOLD (ROS-SIM blocker) |
   | G-8 | 관제 이완 안전 | 관제가 꺼져도 로봇이 로컬 대시보드·e-stop·deadman으로 안전한가 | `test_fleet_agent`(disconnected 계약), `src/hardware/bringup/test/test_command_deadman` | FleetAgent 미연결 계약과 deadman 시험이 존재 | GO (LOCAL) / DEVICE 미측정 |

4. **판정·승격 규칙.** 축의 판정은 (a) 현재 트리에서 재실행 가능한 측정 수단,
   (b) 증거 계층 표기, (c) 근거 파일/로그 링크의 셋을 갖출 때만 쓴다. LOCAL
   증거는 어떤 DEVICE/FIELD 주장도 지지하지 않는다(D-79, D-91, D-152 선례).
   기준선 열은 **스냅샷**이다 — 이 ADR은 기준과 기준선만 소유하고, 이후 회차 결과를
   다시 쓰지 않는다. 회차 결과는 `docs/validation/middleware-goal-<date>/README.md`
   (축별 판정·blocker·근거 링크)에 남긴다(D-153 §4와 같은 방식).

5. **재평가 트리거.** ① `deploy/robot/Dockerfile`·`compose.yaml`·`board.yaml`
   변경 → G-4/G-5. ② safety/command/navigation 소스에 벤더·기기 문자열 추가 → G-6
   즉시 HOLD. ③ fleet ROS-SIM blocker 해제 → G-7 재판정. ④ Pi device readback
   통과 → G-2/G-5/G-8 DEVICE 판정 첫 기록. ⑤ `/cmd_vel` 발행자 수 재실측(G-3).
   트리거 없는 회차는 기록만 남기고 판정을 바꾸지 않는다.

**Alternatives:** 모듈 게이트(STATUS.md)만으로 대체하는 안은 모듈 건강은 재지만
"관문이 단일한가""벤더가 스며들지 않았는가" 같은 축 구조를 직접 재지 않아 목표
판정이 불가능하다. 산문 목표(D-63 한 문장)만 두는 안은 측정 수단이 없어 회의마다
재논쟁이 된다. 합산 점수(가중치 0–100)안은 안전 축(G-3, G-8)이 다른 축의 높은
점수로 상쇄될 수 있어 버렸다 — 전부 GO 또는 미달이 목표의 성질에 맞다.

**Consequences:** 이 표에 따르면 **현재(2026-09-22) 목표는 미달이다** — G-6(안전
코드의 `pinky_calmap227` 잔존)과 G-7(fleet ROS-SIM blocker)이 HOLD이고, DEVICE
증거가 하나도 없어 축 어디에도 실기 판정이 없다. 반대로 무엇이 이미 충족됐는지도
명시된다(G-1·G-8 LOCAL, G-2·G-3 ROS-SIM). 축 표는 새 목표 문서·PR이 "무엇을 하려는
미들웨어인가"를 새로 쓰는 대신 이 표를 갱신하도록 한다.

**Validation / Transition:** 첫 회차(`docs/validation/middleware-goal-<date>/`,
8축 전부 실측 재판정 + 근거 링크)가 이 ADR의 착지 증거이며, 그때 Status를
Accepted로 뒤집는다. G-6 잔존 제거와 G-7 blocker 해제는 각각 소유 모듈(core·fleet)의
게이트가 닫고 이 표의 판정만 갱신한다. 회차 종료 시 `docs/logs.md` 항목 추가와
`python tools/harness/rosy_harness.py generate`를 돌린다.

**References:** [CORE SRS](../spec/ROSY%20CORE%20SRS.md) §1.1·§1.3,
[ADR Log](<../reference/ROSY ADR Log.md>) D-1, D-2, D-8, D-18, D-33, D-38, D-59,
D-61, D-62, **D-63**(모듈형 미들웨어 목표), D-64, D-79, D-81, D-87, D-91, D-126,
D-153(UI/UX 평가표 선례), D-155,
[모듈형 미들웨어 목표 설계](../plans/2026-09-16-modular-middleware-goal-design.md),
[사이트 미들웨어 역할 패브릭 설계](../plans/2026-09-14-site-middleware-role-fabric-design.md),
[ROS-SIM core 회차](../validation/ros-sim-core-2026-09-22/README.md).

---
