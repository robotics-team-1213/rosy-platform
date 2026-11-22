## D-1040 AI assessor clears torque-unconfirmed and wind-up incidents only on a fresh remeasure

**Status:** Accepted (2026-11-17, D-1035의 사용자 결정 "AI가 판정하고 해제한다"를 D-1039 위에 넓힌다; 구현·원격 시험의 수용이며 셀 배포·실물 해제 수용은 별도)

| 결정 | 관계 |
|---|---|
| [D-1039](D-1039-ai-assessor-kind-limited-incident-clear.md) | 넓힌다. 기계 해제 표(4항)에 두 종류를 더하되 새 측정이 있을 때만이다. assessor 자격·팔 지정·근거 필수·하루 한 번·기계 해제 표시는 그대로다. |
| [D-971](D-971-omx-arm-incidents-in-fleet.md) | 따른다. 원장과 사람 해제는 바뀌지 않는다. |
| [D-911](D-911-omx-native-reviewed-operating-envelope.md) | 바꾸지 않는다. 다시 재기는 팔을 움직이지 않고 토크를 켜지 않는다. |

### 문제

2026-11-17 실물 사건 두 개가 D-1039 규칙으로는 사람 몫이었지만, 나중에 읽은 레지스터는 팔이 조용히 접혀 있음을 보였다.
- arm_b 17:10: USB 허브 재열거 중 세션 종료 때 토크 OFF 쓰기가 `Port is in use!`로 실패했다(`runner: session ended: RuntimeError: torque OFF not confirmed: [ConnectionError(... Torque_Enable on id_=11 ...)...]`, 모터 고장 기록 하나는 같은 포트 끊김의 `SerialException`). 뒤의 읽기 전용 레지스터 읽기(`register_probe.py`)에서 ID 11-16 모두 `torque_enabled` 0, `hardware_error` 0, 접힌 위치였다.
- arm_a 18:37: 고아 세션이 접힌 홈을 20분 붙잡는 동안 `joint_push`가 감김을 보았다(`elbow_flex still 0.8 units short, PWM winding up 206 -> 246 of 600: pushing against something`).

두 사건 모두 세션 끝의 사실만으로는 팔의 상태를 확정할 수 없다. 사실을 느슨하게 받으면 진짜 걸림·래치도 풀리므로, 새로 잰 값이 있을 때만 푼다.

### 결정

1. **다시 재기(셀).** `omx_incident.py reassess --arm X --config <그 팔의 셀 설정>`은 그 팔의 팔로워만 읽는다. 장치는 셀의 보드 지도(`/etc/rosy/omx-arm-boards.json`, 보드 시리얼 → 팔)에서 그 팔에 매인 보드가 정확히 하나이고 `/dev/serial/by-id`에 꽂혀 있을 때의 경로이고, `--device`를 주면 그 경로와 같아야 한다. 홈은 `arm_id`가 그 팔인 셀 설정의 `plan_path` 계획에서 읽는다(아니면 거부). 보정 범위는 그 팔의 LeRobot 팔로워 보정 파일(없으면 0..4095)이다. 그다음 살아 있는 팔 lease(`cell_arm_lease`)가 없고 세션 잠금(`session_lock(arm)`)을 얻을 수 있고 포트를 아무도 쓰지 않을 때만(`register_probe`: `fuser`, 배타 열기, 유니캐스트 PING·READ만) 여섯 모터의 토크·하드웨어 오류·위치를 읽는다. 몸통 다섯 관절을 계획 홈과 LeRobot 단위로 비교해 가장 큰 차가 `HOME_TOL`(3.0, 실행기 SETTLE_TOL) 이하일 때만 접힘이다. 셀 화면(A·B는 top·side, S는 `arm_s_top`)의 정지 사진을 `incidents/reassess/`에 sha256과 함께 남긴다. 그 팔의 로컬 사건 기록이 이름 붙인 모터 고장 기록을 다시 읽어 `{name, fault_type, fault}`로 싣는다(보고는 Fleet에 파일 이름만 보낸다). 결과는 `remeasured` 블록 `{arm, board_serial, incident_id, at, torque_after{11..16}, hardware_error{11..16}, folded, max_home_err, frames[{role, sha256}], fault_records}`이다. 팔은 움직이지 않는다.
2. **해제 요청.** `clear` 본문에 선택 필드 `remeasured`(`ArmIncidentRemeasure`, strict, 여섯 모터 모두, 사진 1-2장)를 더한다. `omx_incident.py clear --reassess`가 1을 실행하고 해제하는 사건마다 `incident_id`를 채운 블록을 assessor 토큰(`--token-file` 또는 `ROSY_ARM_ASSESSOR_TOKEN_FILE`)으로 보낸다. `--cause`·`--basis`가 없으면 보내지 않는다.
3. **두 종류(기본 거부).** `machine_clearable(facts, remeasured, since=reported_at, now)`의 두 번째 경로다.

   | 종류 | 저장 사실 조건 |
   |---|---|
   | 토크 OFF 미확인(포트 사용 중) | 표시 행 전부가 `error`·`fault` 전체 `TORQUE_UNCONFIRMED`(선택적 `runner: ` 뒤 `session ended: RuntimeError: torque OFF not confirmed: [` + ID 11-16의 `ConnectionError("Failed to write 'Torque_Enable' on id_=<id> with '0' after <n> tries. [TxRxResult] Port is in use!")` 1-6개 + `]`, ASCII 전체 일치), `caught`·`person_needed` 없음, 감김 없음. 저장된 `torque_after`는 보지 않는다(확인하지 못한 것이 사건이다). 저장된 모터 고장 기록은 이름마다 블록의 `fault_records`에 `fault_type` `SerialException`, `fault` 전체 `device reports readiness to read but returned no data (device disconnected or multiple access on port?)`(`PORT_LOST_FAULT`, 같은 포트 끊김의 pyserial 문구)로 있어야 한다. 과부하·과열·하드웨어 오류 문구나 다른 예외, 블록에 없는 기록이 하나라도 있으면 거부한다. |
   | 끝나기 전 감김 | 감김 행 전부가 `reason` 전체 `WINDUP`(`<shoulder_pan\|shoulder_lift\|elbow_flex\|wrist_flex> still <n.n> units short, PWM winding up <n> -> <n> of <n>: pushing against something`, 조의 "something is in them"은 아님), 표시 행 없음, 저장된 토크 모두 0, 모터 고장 기록 없음. |

   두 종류 모두 래치·접촉 정지가 없고 `safe_end`·`folded`·`caps_restored`가 참이어야 한다. 두 종류가 함께 있거나 다른 행이 섞이면 이 경로가 아니다(D-1039 경로가 거부한다).
4. **새 측정 조건.** `remeasured`가 형태에 맞고, `(arm, board_serial)`이 Fleet 관찰 manifest의 그 사건 출처(`source_id`)의 `(arm_id, board_id)`와 같고, `incident_id`가 해제하는 사건이며, `at`이 그 사건의 Fleet `reported_at`보다 뒤이고 지금보다 60초(시계 차) 넘게 앞서지 않으며 900초보다 오래되지 않고, 여섯 모터 토크 0, 하드웨어 오류 0, `folded` 참, `max_home_err` 3.0 이하일 때만이다. 하나라도 어기면 403 `AI_CLEAR_KIND_REFUSED`다.
5. **그대로인 것.** 팔마다 24시간 한 번(403 `AI_CLEAR_REPEAT_LIMIT`), 팔 지정, `cause`·`basis` 필수, 기계 해제의 근거 `unknown` 저장, 사람 해제. 다시 재기는 다른 종류를 풀지 않는다.
6. **기록.** 기계 해제의 행에만 받은 `remeasured`를 그대로 저장하고 사건 행 `cleared.remeasured`로 보인다. 사람 해제는 블록을 판정하지 않으므로 저장하지 않는다(null). 사진 바이트는 셀에 남고 Fleet은 sha256만 가진다.

**2026-11-17 독립 검토(DISAGREE) 반영:** 포트 종류의 고장 기록 문구 전체 일치, 블록의 팔·보드·사건 묶음(보드 지도와 manifest 대조, 셀 설정의 팔 확인), 사람 해제의 블록 미저장을 같은 날 이 결정에 넣었다(구현 전 수정, 수용 기록 없음).

### 결과

- 2026-11-17의 두 사건 모양은 새로 잰 조용한 팔에서만 사람 없이 풀린다. 새 측정이 없거나, 사건보다 앞서거나, 오래되었거나, 토크가 켜졌거나, 하드웨어 오류가 있거나, 접히지 않았으면 사람이 본다.
- 같은 호스트가 사실과 새 측정을 함께 보고하는 위험은 D-1039와 같다. 고장 기록 문구도 그 호스트가 다시 읽어 보낸 것이다. 새 측정은 그 호스트가 이미 가진 권한(포트 읽기) 이상을 쓰지 않고, 하루 한 번 상한과 저장된 블록이 감사 근거다.
- 다시 재기는 팔이 지금 조용하다는 증거이지 사건 원인의 증거가 아니다. 원인 라벨은 계속 `unknown`이다.
