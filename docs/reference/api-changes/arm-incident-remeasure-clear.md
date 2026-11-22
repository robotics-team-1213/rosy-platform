---
surface: fleet
kind: additive
slug: arm-incident-remeasure-clear
date: 2026-11-21
title: 새로 잰 팔로만 푸는 두 사건 종류 (D-1040)
---
`POST /api/fleet/workcell-observations/arms/{source_id}/incidents/{incident_id}/clear` 본문에 선택 필드 `remeasured`를 더한다(additive). 형태는 strict `ArmIncidentRemeasure` `{arm, board_serial, incident_id?, at, torque_after{"11".."16": int}, hardware_error{"11".."16": int}, folded: bool, max_home_err (0-400), frames[1-2]{role, sha256}, fault_records[<=8]{name, fault_type, fault}}`이고 여섯 모터가 모두 있어야 한다(아니면 422 `INVALID_ARM_INCIDENT_CLEAR`). `(arm, board_serial)`은 그 `source_id`의 manifest `(arm_id, board_id)`, `incident_id`는 경로의 사건이어야 한다. assessor 해제에서 `machine_clearable`의 두 번째 경로가 쓴다. 저장 사실이 토크 OFF 미확인(포트 사용 중: 표시 행 전부가 `session ended: RuntimeError: torque OFF not confirmed: [ConnectionError("Failed to write 'Torque_Enable' on id_=<11-16> with '0' after <n> tries. [TxRxResult] Port is in use!"), ...]` 전체 일치, 저장된 모터 고장 기록마다 블록 `fault_records`에 `SerialException` / `device reports readiness to read but returned no data (device disconnected or multiple access on port?)` 전체 일치)이거나 끝나기 전 감김(감김 행 전부가 `<관절> still <n.n> units short, PWM winding up <n> -> <n> of <n>: pushing against something` 전체 일치, 표시 행 없음)일 때, `remeasured.at`이 사건의 `reported_at`보다 뒤이고 지금보다 60초 넘게 앞서지 않고 900초보다 오래되지 않으며 모든 모터 토크 0·하드웨어 오류 0·`folded` 참·`max_home_err` 3.0 이하여야 한다. 아니면 403 `AI_CLEAR_KIND_REFUSED`. 래치·접촉 정지·안전 종료·접힘·`caps_restored` 조건과 팔마다 24시간 한 번(403 `AI_CLEAR_REPEAT_LIMIT`)은 그대로다. 기계 해제에서만 받은 블록이 해제 행에 저장되어 사건 행 `cleared.remeasured`로 보인다(사람 해제와 블록 없는 해제는 null). 다른 종류와 사람 해제는 바뀌지 않는다.
