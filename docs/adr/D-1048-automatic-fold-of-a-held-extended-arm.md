## D-1048 뻗은 채 멈춘 팔은 막히지 않은 길로 스스로 접고, 접힘을 잰 뒤 기계가 해제한다

**Status:** Accepted (2026-11-19, 사용자 결정 "팔을 뻗은 채 멈춘 사고는 안전하게 접어야지. 접는 경로에 문제가 있다면 이를 피해서 하는 플래닝을 하게 하면 되잖아"; 구현·원격 시험의 수용이며 셀 설정으로 켜기·첫 실물 입회 수용은 별도). 패널(opencode·Claude 하위 에이전트) 원문 `D:/DevTemp/auto-fold-1119/`. [D-1047](D-1047-cell-s-automatic-departure-and-link-failure-clear.md) 위에 얹는다.

| 결정 | 관계 |
|---|---|
| D-1047 | 넓힌다. D-1047은 "팔을 뻗은 채 끊긴 사고"를 이 결정으로 미뤘다. |
| [D-1039](D-1039-ai-assessor-kind-limited-incident-clear.md) | 넓힌다. assessor 해제에 접기 증거(`recovery`)를 더한다. 래치·감김은 계속 사람 몫이고, 하루 세 번 상한은 그대로다. |
| [D-911](D-911-omx-native-reviewed-operating-envelope.md) | 이 경로(보류된 팔을 home으로 접기)에 한해 사람 감독 없는 모션을 사용자가 승인했다. 모션은 모두 러너의 가드 명령(`park`, `jog`)이다. 속도 상한·추종 오차·strain·접촉 hold는 그대로다. 첫 실물 실행은 입회로 수용한 뒤 셀 설정으로 켠다. |
| 규칙 "팔을 뻗은 채 토크를 끊지 않는다" | 지킨다. 길이 없으면 `human-hold`(토크 ON)로 그 자리에 둔다. 토크 OFF는 home에 닿은 뒤의 정상 종료뿐이다. |

### 결정

1. **시작.** 셀이 보고한 보류 사고를 즉시 해제할 수 없으면(D-1047 규칙 불충족), `omx_incident`가 `cell_auto_fold.py launch`를 따로 띄운다. 조건은 `~/.config/rosy/auto-fold.json`에 그 팔이 있을 때만이다. 열린 사고는 하나여야 하고, 사고마다 한 번만 시도한다.
2. **복구 세션.** 팔의 세션 래퍼로 세션을 연다. `refuse_if_held`는 Fleet이 "보류 전체가 이 사고 하나"라고 답할 때만 그 사고 이름(`ROSY_RECOVERY_INCIDENT`)으로 세션을 연다.
3. **접는 길 계획.** 막히지 않은 첫 후보만 실행한다.
   - 집게가 물건을 쥐고 있으면(닫으라고 했는데 4단위 넘게 덜 닫힘), 집게 끝이 낮을 때(clear_z 아래)만 짧은 상승 경로를 검사·예약하고 `release_and_rise`로 놓고 든다. 높은 곳에서 쥔 채면 놓으면 떨어지므로 사람 몫이다.
   - 후보 1은 러너의 park 경로(들기, transit 높이에서 회전, 내리기)다. 후보 2~5는 어깨 회전 +5, −5, +10, −10단위 우회 뒤의 park다.
   - 각 후보를 움직이기 전에 확인한다. 프레임을 FK로 위 카메라 화면에 그려 `cell_corridor.check`(낮은 구간은 모든 덩어리, 높은 구간은 모르는 덩어리: 손·다른 팔)로 보고, 다른 팔 예약과 겹치지 않게 `cell_space`에 예약한다.
   - 막히지 않은 후보가 없거나 어떤 오류가 나면 `human-hold`로 그 자리에 둔다. 보류가 걸린 러너는 자기 유휴 park도 거부하고 토크를 유지한다(`chunk_runner_settle.check_runner_idle`).
4. **성공 판정.** park가 settled이고 몸통 관절이 home에서 3단위 안이다. 그 뒤 `stop`으로 세션이 끝나면 `record_session`이 토크 0을 확인한다.
   - **보완 (2026-11-27):** 이 변경부터 토크 꺼진 팔의 사건 열기 결정(`omx_incident.decide`)은 보정된 라이브러리 자세 기준의 쉬는 자세(몸 관절이 home에서 `REST_TOL` 8 안)를 "펴짐 아님"으로 읽어 guarded 접기 보류를 걸지 않는다. 단 통신 끊김 복구(`is_home_recovery`) 경우는 예전처럼 보류한다. `facts.folded`와 기계 해제(`machine_clearable`)는 3단위 그대로다.
5. **해제.** 증거에는 사고 ID와 측정 시각이 들어간다. assessor 해제 본문에 `recovery`를 싣는다. 내용은 `kind: auto_fold`, `folded_state`, `home`, `torque_after`, `corridor_clear`다. Fleet은 `machine_clearable`이 거부한 사고를 `clearable_after_fold`로 다시 판정하고 증거를 사고 행에 남긴다.
   - **허용:** 접힘이 home 3단위 안이고, 사고가 보고한 home과 같으며, 모든 모터 토크 0이고, 길이 비어 있었고, 사실 목록이 완전하다.
   - **거부:** 래치, 감김, 통신 끊김이 아닌 모터 고장 기록, 사고에 home이 없음, 다른 사고의 증거, 사고보다 오래된 증거(시계 차이 120초 허용), 모터 6개 미만의 토크 확인. 장치가 남긴 원래 복구 기록은 덮어쓰지 않고 함께 남긴다.

   접촉·strain·조 끼임·통신 끊김은 접기로 끝나는 종류다.

### 다음

- 셀 S부터 `auto-fold.json`을 두기 전에 입회 실행 두 번으로 수용한다. 하나는 접촉 정지 뒤 자동 park, 다른 하나는 쥔 채 멈춤 뒤 release_and_rise → park다.
- 관절 공간 경유점 탐색(어깨 회전 외의 우회)과 낮게 막혔을 때의 `cell_unwedge` 들어 올리기는 실물 결과를 본 뒤에 한다(unwedge의 마지막 park는 검사·예약이 없어 이번에는 뺐다).
- 독립 안전 검토(2026-11-19)의 REQUEST CHANGES를 반영했다: transit 키, 검사 없는 움직임, 오류 시 보류, 증거 결속.

### 추록 (2026-11-24): 토크 유지 가드 해제(`recover-unlatch`) · 저속 복귀 파크(`fold-from-hold` / `park-slow`) · 다중 VLM/LLM 복구 패널

- **배경:** 2026-11-24 사용자 결정("물리지지 없이 하는 걸로 잡아볼래? agy 나 기타 llm ai vlm 다 사용해도 좋아") 및 `omx-return-home`(`91c88cef35`, `3e97f67bd8`, `e655b7bc97`) 핵심 안전 보강 병합. 기존 세션이 이미 `human_hold_latched` 상태에 들어가 있을 때 토크를 끊지 않고(`팔을 뻗은 채 토크를 끊지 않는다` 불변식 준수) 물리적 사람 손 지지 없이 안전하게 홈으로 복귀하는 경로를 통합한다.
- **저속 복귀 파크 및 상승 우선 파크 (`chunk_library.py`, `chunk_runner_guards.py`, `chunk_runner_recover.py`, `chunk_runner_settle.py`):**
  1. `OPEN_JAW_MARGIN = 8.0`: 열린 집게(`> grip_transit + 8.0`)는 저고도에서 닫지 않고 transit 높이까지 먼저 상승한 뒤 닫으며, 이미 물건을 쥔 집게(`<= closed + 8.0`)는 닫힘 우선 순서를 유지한다.
  2. **`checked ... fold-from-hold <6축>` 및 `park-slow` (`RECOVERY_PARKS`):** transit speed `<= 0.3`의 저속 가드 파크다. 두 명령 모두 점유 그리퍼(`holding` 또는 미닫힘 오차) · 비가용 온도(`>= 65°C`) · 하드웨어 오류 · 토크 미인가를 거부하며, `fold-from-hold`는 `checked` 세션/라이브러리 바인딩 + `human_hold_latched` + `torque_hold_commanded` + 소수 둘째 자리 실측 6축 일치까지 요구한다. 실행 중 `stop` 등 다른 명령은 거부되고(`human-hold`·`state`만 허용), 접촉/집게 밀림/열·스톨/추종 오차(`FOLLOW_STOP` 1 s) 또는 정착 타임아웃(`error <= 3.0` 및 비진동 필수) 시 `RuntimeError`로 토크를 끄지 않고 **토크 ON 상태로 `human-hold`를 재래치**한다.
  3. **`recover-unlatch` + `park-slow`:** 우회(`pan±5/±10`, `lift_first` 등)나 저고도 `release_and_rise` 또는 다중 VLM/LLM 제안이 필요한 경우, 먼저 `look` · `load_check` · `cell_space.reserve`(TTL 360 s)로 경로를 예약한 **뒤에만** `recover-unlatch`를 호출하고 `park-slow`로 복귀한다.
  4. **공간 예약 보존:** `cell_auto_fold`는 이미 팔이 움직인 뒤 실패(`PARK_NOT_HOME`, `DETOUR_REFUSED`, `RELEASE_STUCK`)하면 다른 팔이 진입하지 못하도록 TTL 만료 전까지 `cell_space` 예약을 해제하지 않는다(이동 전 거부/성공 시에만 해제).
- **다중 VLM/LLM 복구 패널 (`judge_seat.py` · `cell_recovery_advisor.py`):**
  - 1차 결정론적 우회 후보가 모두 막히면 `judge_seat.cooperate` 기반 다중 VLM/LLM 패널(`--vlm-config` / `--vlm-url`, 문자열·딕셔너리 모두 타임아웃 상한 `30.0 s`)을 호출한다. 패널은 최소 1개의 비전 모델(`qwen3-vl:8b-instruct` 등)을 필수로 포함하고, 스키마 예약 메타 키(`role`/`model`/`deliberation`/`consensus`) 위조를 거부하며, 의견 충돌 시 중재자(`arbiter`) 또는 보수적 동률 규칙(`escalate_human` 최우선)으로 수렴한 뒤 `translate_proposal` + `cell_corridor` + `cell_space` 게이트를 통과해야만 실행한다.
- **파이프라인 작업 통합 (`cell_job_spec.py` · `cell_job_api.py` · `cell_job_peer_health.py`):**
  - `recover_hold` 작업은 `live.json`의 `human_hold_latched` · `torque_hold_commanded` · 생존 세션 락/생존 PID 및 `check_peer_ab_folded` · D435 잠금 · AMR 침대 게이트를 검증한다(`ROLE_MACHINE`은 하드웨어 입회 수용 전 403 차단).
  - **운용 한계:** 본 패치 이전에 메모리상 구버전(`omx-tools-61f8d8919a`)으로 이미 떠 있는 레거시 세션(`recover-unlatch`/`fold-from-hold` 미탑재)은 실행 중 코드 교체 없이 해제할 수 없으며, 새 릴리스 배포 이후 시작된 세션부터 무지지 토크 유지 복구가 적용된다.
