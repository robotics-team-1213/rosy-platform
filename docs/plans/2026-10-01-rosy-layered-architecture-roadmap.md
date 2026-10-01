# ROSY 계층 아키텍처 로드맵 (D-399 후속)

**범위:** [D-399](../adr/D-399-rosy-layered-architecture-site-plane-device-pipeline.md)가 정한 배치를 실제 산출물로 옮기는 부모 계획이다. 각 단계는 자기 하위 계획(spec → plan → 구현)을 따로 갖는다. 이 문서는 순서, 의존, 게이트, 하위 계획의 위치만 정한다. 이 문서 자체는 어떤 게이트도 올리지 않는다.

**첫 수용 목표:** Gazebo OMX-F가 Rosy Cell 레시피대로 소형 박스 2층을 적재한다(슬립시트 1장, 팔레트 2개를 차례로). 실물 OMX, DEVICE, FIELD는 이 로드맵의 범위가 아니다.

## 결정된 전제

| 항목 | 결정 | 출처 |
|---|---|---|
| 층 배치 | Application(사이트) → Fleet → 장치별 장치 미들웨어(D-296 이름) → Drivers | D-399 §1 |
| CORE의 뜻 | 장치 런타임 이름. Mission·Task는 Fleet | D-399 §1, D-12, D-70 |
| 미들웨어 | 장치 내부 CycloneDDS, 사이트↔장치 REST/WSS/UDS. Zenoh는 격리해서만 | D-399 §3, D-117 |
| AI | 숙고형은 사이트 제안, 반응형 정책은 장치의 엔벌로프 스킬 | D-399 §2 |
| LeRobot | 운영 모드에서는 추론 엔진뿐이고 ROS owner가 버스를 소유. 녹화/개발 모드에서만 LeRobot이 버스 소유 | D-299 |
| 경로 계획 | MoveIt 2 채택. 위에서 수직으로 잡는 5축 IK 필요 | 이 대화의 사용자 결정, 후속 ADR |
| 팔레타이징 범위 | 단일 SKU, 격자/혼합(split)/미러 인터락, 슬립시트, 다중 팔레트, 디팔레타이징 | 사용자 결정 |
| 앱 | Rosy Cell, `src/site/cell`, 패키지 `rosy_cell` (D-377). Job은 Fleet에 Mission으로 제출하고, Step 하달은 Fleet이 한다 | D-399 §5, D-336 |
| OMX-F 사양 | 5축+그리퍼, 가반하중 풀리치 100 g / 일반 250 g (ai.robotis.com/omx/hardware_omx.html, 2026-10-01 확인). `open_manipulator` jazzy 5.1.3에 `omx_f` MoveIt 설정(KDL `position_only_ik: True`) | ROBOTIS 1차 출처 |

## 단계

```text
P0 D-399 착지 ─┬─ P1 ADR: Rosy Cell · Motion Intent · OMX 장치/티칭 API ── P2 Rosy Cell 코어(SOURCE)
               │                                             │
               ├─ P3 ADR+구현: MoveIt / OMX-F Gazebo ────────┼─ P4 OMX Step 실행 API(ROS-SIM)
               │                                             │        │
               │                                             └────────┴─ P5 Rosy Cell 서버·마법사(ROS-SIM 수용)
               ├─ P6 ADR+구현: 장치 Lifecycle/Fault
               └─ P7 ADR+구현: 반응형 정책 엔벌로프 스킬(LeRobot) · 리더 팔 티칭
```

### P0. D-399 착지

- 독립 리뷰 지적 사항을 반영한다. 리뷰어 판정은 approve 또는 approve-with-fixes여야 하고, fix를 반영한 뒤 재확인한다.
- [01 Target Architecture](../architecture/01_ROSY_OS_Target_Architecture.md), [11 AI](../architecture/11_ROSY_AI_and_Physical_AI.md), `CONCEPTS.md`의 용어를 D-399 §6 대응표에 맞춘다. 문서만 바꾸고 코드는 건드리지 않는다.
- 게이트: `python tools/harness/rosy_harness.py lint` 오류 0, `python -m pytest test/architecture -q` known_failures 대비 NEW 0.
- 브랜치: `docs/d399-layered-architecture`.

### P1. ADR 세 개 (Proposed)

1. **Rosy Cell 애플리케이션**
   - 셀 설정(`cell.yaml`: 3점 프레임, 스테이션, 접근 여유)과 레시피(`recipe.yaml`)를 분리한다.
   - 레시피는 검증할 때 셀 설정의 해시를 고정한다. 셀 설정이 바뀌면 그 레시피는 재검증 전까지 실행할 수 없다.
   - Job = Step 목록(`pick`/`place`/`pallet_done`).
   - 사이트에 둔다. Rosy Cell은 Job을 **Fleet에 Mission으로 제출**하고, Fleet이 승인(D-330)한 뒤 Step을 장치에 하달한다. Rosy Cell이 장치에 직접 제출하지 않는다(D-399 §5, D-336 §2).
2. **Motion Intent 공통 스키마와 장치별 Arbiter 우선순위 표**
   - Step(사이트 → 장치)과 Motion Intent(장치 안의 스킬 → Arbiter)를 구분한다.
   - D-399가 고정한 것은 정지 계열(EMERGENCY, SAFETY)이 모든 동작 출처보다 위라는 것뿐이다. MANUAL 위치와 진행 중 OMX phase 선점(D-376 §6)은 이 ADR이 정한다.
3. **OMX 장치·티칭 API**
   - D-282 §5가 요구하는 OMX 원격 API 계약이다. 셋업·티칭(관절 jog, 리더 팔, 포인트 저장)과 도달성 조회를 다룬다. lease, 인증, 데드맨, 녹화 모드에서의 거부를 함께 정한다.
   - P3의 도달성 서비스와 P5의 셋업 마법사가 이 ADR에 의존한다.

번호는 쓰기 직전에 `rosy-land-on-main`의 ADR 번호 절차로 정한다. **P2는 P0가 main에 들어간 뒤 시작한다.** `progress.md`의 `adrs: [D-399]`가 harness lint의 unknown-ADR 검사를 통과하려면 D-399가 main에 있어야 하기 때문이다.

### P2. Rosy Cell 코어 (ROS 없음, SOURCE)

- 하위 계획: [2026-10-01-rosy-cell-pattern-core.md](2026-10-01-rosy-cell-pattern-core.md).
- 산출물: 프레임(3점), 박스/팔레트, 패턴(grid·split·mirror), 적층(슬립시트), 적재 순서, 레시피/셀 로더(스키마·해시), Job 컴파일러.
- 게이트: `python -m pytest src/site/cell/test -q` 통과, 아키텍처 테스트 NEW 0, progress SOURCE GO.

### P3. MoveIt 2 채택과 OMX-F Gazebo (ADR + 구현)

- ADR: D-376의 플래너 HOLD를 푸는 조건과 MoveIt 2 채택 범위를 정한다(계획만, 제출은 owner). 아래 IK 두 후보를 비교한 결과를 근거로 둔다.
  - IK 후보 ①: `pick_ik`(자세 가중치)
  - IK 후보 ②: 위에서 수직으로 잡는 전용 해석 IK 플러그인
  - 참고로 ROBOTIS 기본 설정은 KDL `position_only_ik: True`라서 박스 yaw를 맞출 수 없다.
- 구현:
  - `open_manipulator`(jazzy, 5.1.x)의 `omx_f_gazebo.launch.py`와 `omx_f_moveit.launch.py use_sim:=true`를 묶는 런치를 만든다.
  - 그리퍼 mimic 제약을 확인한다. 현재 ROS-SIM HOLD 사유가 이것이다.
  - 도달성 검사 서비스(포즈 목록 → 포즈마다 가능/불가)를 OMX owner 쪽에 둔다.
- 게이트: ROS-SIM에서 Rosy Cell 2층 Job의 모든 place 포즈가 도달 가능하다는 결과, 그리고 한 writer 확인.
- 겹치는 작업: `.worktrees/omx-pick-place-execution`, `omx-phase-coordinator`, `omx-sim-phases`, `omx-sim-stop-closure`. 시작 전에 `ListAgents`로 담당 세션을 확인한다.

### P4. OMX Step 실행 API (ROS-SIM)

- Fleet이 Rosy Cell Mission의 Step을 D-336 UDS Action API로 OMX owner에 하달하는 경로를 추가한다. UDS의 호출자는 계속 Fleet 서비스 UID 하나뿐이다. 함께 갖출 것은 다음과 같다.
  - lease
  - Job 해시 확인
  - 일시정지/재개/취소
  - D-386 phase 상태
  - 녹화(LeRobot) 모드일 때 lease 거부
- Step `pick`/`place`는 장치 안에서 MoveIt 계획 → owner 제출 → 그리퍼 readback으로 실행한다(D-376).
- 게이트: ROS-SIM에서 Step 하나가 실패하면 HOLD하고, 재개하면 다음 Step부터 이어서 실행되는지 확인한다.

### P5. Rosy Cell 서버와 셋업 마법사

- FastAPI와 정적 UI를 둔다. UI는 `web_common` 토큰을 쓰고 DESIGN.md를 따른다.
- 셋업 마법사 단계: 셀 연결 → 툴 → 그리퍼 → 티칭 방식 → 프레임(3점) → 스테이션 → 공통 포즈.
- 레시피 편집기는 2D 패턴 미리보기와 검증 결과를 보여 준다. 실행 화면에는 카운터, 일시정지, HOLD 표시를 둔다.
- **수용(로드맵 목표):** Gazebo에서 2층, 슬립시트 1장, 팔레트 2개 Job을 끝까지 실행한다. 증거는 `docs/validation/`에 둔다.

### P6. 장치 Lifecycle·Fault 계약 (ADR + 구현)

- 흩어진 조각을 하나의 장치 Fault 계약으로 묶는다. 대상은 D-32 오류 코드, `core_features/{recovery,diagnostics}`, `rosy-hw-probe`, 장치 카드, commissioning이다.
- 사이트 집계 형식도 함께 정한다. Pinky와 OMX가 같은 형식으로 보고해야 한다.

### P7. 반응형 정책 엔벌로프 스킬과 리더 팔 티칭 (ADR + 구현)

- ADR 내용:
  - 엔벌로프(영역, 시간, 속도/스텝, 종료 조건)
  - 정책 출력 → Motion Intent → Arbiter
  - 녹화 모드 전환(D-299 절차)
  - LeRobotDataset v3 변환 매핑 표
- 구현 순서는 D-273을 따른다. 먼저 페이크 정책으로 엔벌로프 시험을 하고, 규칙 기반 pick 기준선 → ACT 비교 순으로 간다.
- 리더 팔(OMX-L)은 읽기 전용 Teach 스킬로 쓴다. 저속 lease를 쓰고, 데드맨을 떼면 정지하며, 포인트는 팔로워 FK로 저장한다.

## 위험

| 위험 | 대응 |
|---|---|
| 5축에서 수직 하향 + yaw IK가 작업 영역 일부에서 풀리지 않음 | P3에서 IK 후보를 비교하고, 도달 불가 포즈는 P2 컴파일 결과에 표시하도록 P5에서 연결 |
| OMX-F 가반하중(풀리치 100 g)이 시연용 박스에 비해 부족 | P5 수용 박스는 50 g 이하 폼 블록으로 하고, 질량은 레시피 `max_load_kg` 검사에 넣음 |
| 동시 세션이 OMX 브랜치를 여럿 운영 중 | P3·P4 시작 전에 담당 세션과 합의하고, 독립 리뷰 후 병합(cross-session ADR review) |
| ROS-SIM HOLD(그리퍼 mimic) | P3의 첫 작업으로 확인. 해결이 안 되면 그리퍼를 단일 조인트로 단순화한 시뮬 모델을 쓰는 방안을 ADR에 기록 |
