# OMX 1·2팔 공통 프로필, 양팔 확장(단기→동시·Fine) 및 카메라 투영 트윈 구현 계획

Date: 2026-11-15  
Status: **Ready — D-1033 구현 계획**  
근거 결정: [D-1033](../adr/D-1033-omx-per-arm-profile-bimanual-and-twin-plan.md) · [D-983](../adr/D-983-two-arm-timing-on-fixed-paths.md) · [D-782](../adr/D-782-omx-action-conditioned-world-model.md) · [D-856](../adr/D-856-application-action-boundary.md) · 작업공간 기록(`Rosy/docs/workspace-records/2026-11-14/three-arm-coordination-design.md`, `Rosy/docs/research/2026-11-14-r2s-map-calibration/report.md`)

---

## 0. 전체 로드맵 (단계별 소유·게이트)

```
[Phase 1: 코드 정렬·게이트 — 사람 불필요, 데모 전]
  ├─ P1-1: grasp_planner TCP 우선순위 역전 + cell_two_arm 팔별 kin 분리 + TCP 불일치 거부
  ├─ P1-2: fit-camera 가드(--params both 기본 차단, cell_depth_pose 선행 확인)
  └─ P1-3: omx_real2sim / omx_map_gate 스냅샷 frame="W" + D-856 P1 조회 형식 정리

[Phase 2: 현장 실측·복구 — 사람/감독 실행 필수, 11/21 데모 직렬 3단 수용]
  ├─ P2-1: [사람] top(D435)·side·arm_b 손목 카메라 USB 복구
  ├─ P2-2: [사람+에이전트] arm_a fingertip_m 실측 + wait(side) 자세 1회 감독 실측
  └─ P2-3: [에이전트+감독] 직렬 3단(증분 A) --plan-only → 시뮬 → D-911 실물 1·2·3단 수용

[Phase 3: 데모 뒤 확장 — A/B 동시 동작(증분 B) & 벨트 인계(증분 C)]
  ├─ P3-1: cell_two_arm.execute on_segment_done 재계산(plan(start=...)) + 실행 중 Gate.open 연결
  ├─ P3-2: wait(side) 스윕 캡슐 검증 + 재취급·반출 이동에서 직렬 vs 동시 시간 이득 실측 비교
  └─ P3-3: 증분 C 벨트 인계(5사건 사슬, arm_s top 벨트 끝 관측, transit_s 실측)

[Phase 4: 데모 뒤 확장 — Fine 스택 양팔 탑재 & Harbor-Twin 상시 연결]
  ├─ P4-1: cell_hooks 정적 마진 상한 B 계약(정지 창 + clearance(sweep ⊕ B, wait) ≥ margin_m)
  ├─ P4-2: 양팔 cell_look / cell_pinch / cell_feel 탑재 (grasp_servo는 별도 수용 뒤)
  ├─ P4-3: omx_twin.py live 정지/청크 경계 카메라 이동 감시 → Fleet HOLD 근거(D-782 W4+D-430)
  └─ P4-4: Harbor D-856 P1 사전 검증 조회(REJECT/HOLD) + UI 트윈 오버레이/ALARM 표시 연결
```

---

## Phase 1: 코드 정렬 및 안전 게이트 (데모 전 즉시 착수 가능)

### 1.1 1팔·2팔 TCP 정본 분리 및 `cell_two_arm.py` 팔별 `kin` 분리
- **목표**: 새 프로필 스키마를 만들지 않고 `cell_auto_setup` + `cell-robot-profile.v1` + `arm-cal-<arm_id>.json` 정본만으로 양팔이 서로 다른 집게/TCP 길이를 쓰게 한다.
- **수정 대상**:
  - `deploy/robot/omx/grasp_planner.py:60`: `os.environ.get("ROSY_OMX_TCP_X_M") or tcp_x_m` → `tcp_x_m if tcp_x_m is not None else os.environ.get("ROSY_OMX_TCP_X_M")` (계획 시 `plan["tcp_x_m"]` 우선; 미지정 시 Arm S 호환 fallback 유지).
  - `deploy/robot/omx/cell_two_arm.py:21-22, 363-367`:
    - 팔별 `tcp_x_m`을 `configs[n]["_arm_calibration"]["z_profile_mm"]["tcp_v21_x_mm"] / 1000.0` (또는 `configs[n].get("tcp_x_m")`)에서 읽어 `kins = {n: load_kinematics(None, tcp_m[n])[0] for n in ORDER}` 생성.
    - 각 라이브러리 `library.get("tcp_x_m")`이 해당 팔의 실측 TCP와 허용치(예: `1.0 mm`) 이상 다르면 `SystemExit`로 실행 전 거부.
    - `poses_of`, `route`, `carry_route`, `execute` 내 `safe_fold`가 `kins[n]`을 쓰도록 수정(shortcut 주석 제거).
- **검증**:
  - 원격 pytest (`test/test_omx_two_arm*.py`, `test/test_omx_grasp_planner*.py` 등 해당 시험 + 신규 회귀 테스트: `arm_a`와 `arm_b`의 `tcp_x_m`이 다를 때 스윕 캡슐이 서로 다른 길이로 계산되고, `plan["tcp_x_m"]` 불일치 시 거부되는지 검증).

### 1.2 `omx_twin.py fit-camera` 파라미터 상쇄 방지 가드
- **목표**: 작업공간 기록(`Rosy/docs/workspace-records/2026-11-09/omx-twin-night/findings.md`)에서 확인된 동시 최적화 악화(`4.5 → 6.3 px`) 재발 차단.
- **수정 대상**:
  - `tools/sim/omx_twin.py`: `--params both`는 명시적 `--allow-coupled-fit` 플래그 없이는 거부하고, 기본 권장 경로를 `cell_depth_pose`(카메라 높이/기울기 고정) → `fit-camera --params joints`로 안내·강제.
- **검증**: `test/test_omx_twin.py` 원격 pytest 통과.

### 1.3 `omx_real2sim.py` / `omx_map_gate` 기준 단일성 게이트 정리
- **목표**: `feat/omx-sim-dock-v24-loop`의 `omx_map_gate.py`가 착지된 뒤, `frame="W"`(`docks-photo` 189.8 mm 기준)와 항목별 `2σ` 판정을 D-856 P1 조회가 읽을 수 있는 JSON 계약(`status: pass|unverified|reject`, `reason`, `sigma_mm`)으로 노출.
- **수정 대상**: `tools/sim/omx_real2sim.py`, `tools/sim/omx_map_gate.py` (착지 후 별도 브랜치).

---

## Phase 2: 현장 복구·실측 및 11/21 직렬 3단 수용 (데모 마일스톤)

> 아래 2.1·2.2는 사람/현장 입회 필수 단계. 완료 전까지 양팔 실물 동시·Fine 동작은 금지한다.

### 2.1 카메라 복구 및 고정
- **사람**: 관제 PC에서 top(D435)·side(Jieli)·`arm_b` 손목 카메라 USB 재연결 및 역할 확인.
- **에이전트 검증**: `cell_depth_pose.py measure`로 top 카메라 높이/기울기(±0.6 mm / ±0.6°) 기준 스냅샷 생성 및 `omx_real2sim.py capture` 정상 프레임 확인.

### 2.2 양팔 필수 기하 실측
- **arm_a `fingertip_m` 측정**: `arm_a` 집게 끝 길이를 CAD/실측으로 확정해 `arm_a` config(`fingertip_m`)와 `arm-cal-arm_a.json`에 반영.
- **`wait(side)` 자세 1회 감독 실측**: 바깥쪽으로 비켜 세운 대기 자세 청크(`wait`)를 1회 티칭·실측하고, **토크 OFF 시 안전성(D-983 미결 4항)** 및 D-911 `operating_envelope` 반영.

### 2.3 직렬 3단(증분 A) 시뮬 → 실물 수용
- **시뮬**: `omx_two_arm_plan.py compare --scenario stack --tier 3` + `omx_two_arm_teacher.py run plan` (`--concurrent` 없음, 3단 완료 · 링크 접촉 0 · 매 인계 뒤 복귀).
- **실물**: `cell_two_arm.py --plan-only` 통과 확인 후 `cell_cycle`(또는 직렬 3단 감독 실행)로 D-911 시도 원장·remap·envelope 거쳐 1·2·3단 순차 수용.

---

## Phase 3: 데모 뒤 확장 — A/B 동시 동작(증분 B) 및 벨트 인계(증분 C)

### 3.1 `cell_two_arm.execute` 재계산 및 실행 중 Gate 연결 (증분 B)
- **내용**:
  - `cell_two_arm.execute`의 `on_segment_done(name, segment, done)` 콜백에 `coordination.plan(..., start=(done["a"], done["b"]))` 재계산 연결 (`plan_gen` 단조 증가, 재계산 실패 시 `replan_none` 결합 정지, 직렬 폴백 금지).
  - 동시 실행 중 새 라이브러리/세그먼트 전환 시에도 `Gate.open` 평가가 빠지지 않도록 `execute` 진입부·재계획 경계 검증 통일.
  - `wait(side)` 청크의 스윕 캡슐(`swept_volume.capsules`)을 `admit()`에서 필수 검증.
- **채택 게이트**: 벨트 적층이 아니라 **재취급·반출 이동** 시나리오에서 MuJoCo 및 실물 사이클 시간이 직렬 대비 유의미하게 단축될 때만 동시 모드 활성화.

### 3.2 벨트 인계 자동화 (증분 C)
- **내용**:
  - `feat/omx-three-arm-pipeline`의 `cell_belt_handover.py`와 `cell_cycle.py` 착지 상태 기준으로 5사건 사슬(`slot_reserved → S_placed → end_observed → AB_grasped → belt_empty_verified`)을 실물 셀에 연결.
  - `arm_s` top 카메라의 벨트 끝 가시성·컨테이너 방향 변동 처리 및 벨트 순환 시간 `transit_s` 실측.
- **게이트**: `unknown` 판독 시 `S HOLD`, 시간창 초과 시 `belt_missing`으로 사람 호출 1회 후 정지.

---

## Phase 4: 데모 뒤 확장 — Fine 스택 양팔 탑재 & Harbor–디지털 트윈 상시 연결

### 4.1 Fine 스택 양팔 탑재 계약 (`cell_look` · `cell_pinch` · `cell_feel`)
- **핵심 제약**: `coordination.py`의 간격 증명은 고정 경로·고정 `rest` 자세를 가정하므로, Fine 훅이 호버나 하강 위치를 바꾸면 스윕 증명이 깨진다.
- **구현 단계**:
  1. **정지 창 강제**: 상대 팔이 `wait(side)` 또는 세그먼트 경계에 정착(`joint_jitter.settled_state` 확인)한 직렬 창에서만 Fine 훅 진입 허용.
  2. **정적 마진 상한 `B` 선언**: 각 훅이 최악 보정 변위 `B`(예: `cell_look`의 `look.max_total_mm`, `cell_pinch`/`cell_feel` 오프셋)를 노출하고, `clearance(계획 스윕 ⊕ B, 상대 wait 자세) ≥ margin_m` 통과 시에만 Fine 허용. (거부율이 과도하면 2단계로 정지 창 내 실제 보정 경로 재검증으로 완화.)
  3. **재계획 경로 Gate**: `cell_look`이 새 라이브러리를 쓰면 `Checked(cell, session_id, library_sha256)` 세션 안에서 `Gate.open` 재평가 후 하강.
  4. **`grasp_servo` 보류 및 단계적 도입**: 조그 기반 `grasp_servo`는 조그 정착 대기 및 팔별 손목 카메라 역할 검증이 끝난 뒤 마지막에 탑재.

### 4.2 `omx_twin.py live` 정지/청크 경계 감시 & Fleet HOLD 배선
- **내용**:
  - `omx_twin.py live`를 운동 중 폐루프 제어가 아닌 **정지/청크 경계 카메라 이동 감시기**(top/side 3 px, wrist 5 px 초과 연속 시 ALARM)로 배치.
  - ALARM을 Fleet `HOLD` 사실로 올리는 배선은 D-782 W4 + D-430 Safety 심의 절차를 거쳐 적용(예측은 `REJECT`/`HOLD`만 가능, `PERMIT` 금지).

### 4.3 Harbor ↔ ROSY D-856 P1 조회 & UI 트윈 가시화
- **Harbor 측 (`harborlogi/`, 별도 팀 PR 절차 준수)**:
  - `harbor/rosy_http.py`·`harbor/outbound.py`에서 D-856 P1 사전 검증 조회를 통해 ROSY `omx_map_gate` / `cell_two_arm --plan-only`의 `REJECT`/`HOLD` 상태를 반영(허용·장치 명령 권한은 추가하지 않음).
  - UI 화면에 트윈 오버레이/카메라 이상 `HOLD` 사유를 증거(read-only)로 표시하되, 보정 입력은 ROSY `real2sim`·`cell_requests` 경로로만 유도.

---

## 검증 및 착수 체크리스트

- [ ] **Phase 1 코드 착지 전**: `remote_pytest.py`로 `test/test_omx_twin.py`, 양팔 계획·실행 관련 테스트, 신규 TCP 분리/가드 테스트 전수 통과 확인.
- [ ] **Phase 2 실물 전**: `deploy/robot/omx/AGENTS.md` 4검사(경로 충돌, 실측 caps 대비 부하 50% 플래그, 중간 정지 복구, strain watch + `state.fault` 확인) 및 비작성자 동의.
- [ ] **Phase 3·4 확장 전**: `arm_a` `fingertip_m` 및 `wait(side)` 실측 완료, 카메라 3대 정상 응답 및 손목 카메라 역할 대응 확정.
