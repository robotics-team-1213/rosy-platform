## D-1077 입회 요구를 실행 직전 측정하는 정지 능력 증명으로 바꾼다 (D-911·D-1024·D-793 보충)

**Status:** Accepted (2026-11-27, 사용자 지시 "입회 요구는 최대한 걷어내고 기록은 유지, 병목 자체를 없애라"; 패널 판정 A·E, `presence-removal-panel-1127/verdict.md`). 구현은 이 ADR과 같은 PR이다. 실물 수용은 남았다.

### Context

D-911 4절은 감독 시험을 `--commissioning --person-at-switch`로 구분했고, D-1024 L3는 스위치 옆 감독자를 요구했다. 그런데 이 값은 요청 JSON의 불리언이거나 사람이 친 플래그다. 시스템이 사람을 볼 수 없으니 "있다"는 말만 남고, 사람이 없는데도 입회가 막아 선 작업이 많았다. 정지를 사람 손에만 둔 것이 병목이었다. 지금은 러너가 lease 감시(#1006)로 스스로 HOLD하고, 사고 자동 해제(#1001·#1009)와 접힘 판정(#1010)이 있다. 정지 능력은 측정할 수 있다.

### Decision

1. **D-911 4절.** "`--commissioning --person-at-switch`" 요구를 "실행 직전 owner(러너·세션)가 측정하는 일회성 정지 능력 증명"으로 바꾼다. "저장된 JSON은 현장 사람의 존재를 주장할 수 없다"는 유지하고 강화한다. 증명은 요청 값이 아니라 측정값이다. 요청이 `person_at_switch`를 보내도 무시하고 감사에만 남긴다. 요청 JSON에 새 불리언을 두지 않는다.
2. **증명 항목(`cell_stop_proof`).** 모두 통과해야 하고 하나라도 실패하면 사유 코드와 함께 거절한다.
   - fault·래치·contact가 없고 chunk가 끝나 정지한 상태(live.json이 신선할 때), 접힘 또는 검증된 홈. live.json이 낡았고 세션·lease가 없으면 신선한 모터 건강 스냅샷의 토크 꺼짐·접힘으로 대신한다.
   - Fleet 안전 조회(`check_fleet_safety_online`)에서 estop·human_detected가 없다. Fleet에 닿지 않으면 기존대로 막지 않는다.
   - 원격 정지 경로가 있다. 러너가 live.json을 발행하거나 Fleet에 닿는다.
   - 증명 시각과 job id·팔이 묶인다. 실행마다 새로 측정하며 재사용하지 않는다. 감사 `audit.jsonl`에 통과·거절 모두 남긴다.
3. **D-1024 L3.** "D-911 감독자가 전원 스위치 옆에 있어야 한다"를 "원격 정지 경로와 실행 lease(#1006)"로 바꾼다. 제안자≠승인자, 승인 창, lease 1초(상한 2초)는 그대로다.
4. **D-793 HOLD 해제.** 사람 확인 없는 HOLD 뒤 재시도 금지는 유지하되, 규칙 id가 정한 자동 해제(#1001·#1009)와 무이동 거절 뒤 자동 recover_hold를 해제 경로로 명시한다. 무이동 거절은 `next=recover_hold`를 남기고, 셀 작업 API는 증명이 통과하면 같은 팔에 recover_hold를 한 번만 잇는다. 결과는 감사에 남는다.
5. **D-935는 바꾸지 않는다.** `payload_check`도 그대로다.
6. **적용 범위.** 증명은 셀 작업 API 경로와 `cell_policy_drive`에 적용한다. API는 증명이 통과한 뒤에만 하위 스크립트에 `--commissioning --person-at-switch` 플래그를 붙인다. `cell_envelope`의 감독 시험 분기는 수동 stage CLI의 `{"person_at_switch": True}`(한계 최초 탐색)와, 이 프로세스가 직접 측정한 증명만 받는다. 파일이나 요청에서 온 증명 dict는 받지 않는다. 자동 recover_hold는 사람 주체가 시작한 작업에만 잇고 기계 토큰에는 잇지 않는다. 자동 recover_hold는 그 작업 자신의 거절이 남긴 hold(`hold_kept`, `reason_code`)이고 작업 종료 10초 안일 때만 잇는다. 사람이 나중에 거는 정지는 live.json에서 구분되지 않아 이 창 밖이면 잇지 않는다. 복구 증명은 `human hold` 래치만 면제하고 contact·하드웨어 fault·진행 중 chunk는 거절한다.
7. **사람에게 남기는 일.** 래치 해제, 케이블, 고공 파지, 한계 최초 탐색(`cell_step`·`cell_push`·`touch_survey`·marks)은 사람이 한다. 한계 최초 탐색은 `--person-at-switch`를 그대로 요구한다. 카메라 사람 감지는 차단 전용이며 입회를 대신하지 않는다.

### Consequences

- 기계 토큰이 `person_at_switch`를 주장해 403을 받던 규칙은 "증명 없는 실행 거절"로 바뀐다. 검토 없는 이동 작업을 기계 토큰이 못 시작하는 규칙(D-1024)은 그대로다.
- 하위 스크립트의 `--person-at-switch` 플래그 이름은 호환 때문에 남는다. 셀 작업 API가 증명 통과 뒤에만 붙인다.
- 한계: `cell_policy_drive`를 ssh로 직접 실행하면 Fleet 조회가 없고(API가 한다), 홈 확인은 기존 `cell_policy_pre_home`에 맡긴다. 원격 정지 경로는 러너 명령 채널(live.json 신선) 또는 Fleet 도달이며, 둘 다 형식 검사가 아니라 관측이지만 Fleet이 꺼진 신선 live 경로는 러너 채널만 본다.
- 기각: 요청 JSON의 `unattended_guarded` 같은 새 불리언(요청 값이라 존재 주장과 같다), 카메라 사람 감지로 입회 대체.
- 일일 지표: 증명 거절 사유별 건수, 거절→다음 작업 간격, 자동 recover_hold 수와 결과.
