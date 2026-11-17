## D-1039 AI assessor service principal and kind-limited incident clear

**Status:** Accepted (2026-11-17, D-1035의 사용자 결정 "사람 해제가 필요없는게 이제 파이프라인으로 ai 가 확인해서 상황판단해서 처리하기로 했어"의 Fleet 쪽 이행; 구현·원격 시험의 수용이며 관제 PC 배포·assessor 토큰 발급·실물 수용은 별도)

| 결정 | 관계 |
|---|---|
| D-1035 (착지 전 브랜치 `feat/calibration-arm-lease-and-jobs`) | 이 기록이 이행한다. D-1035는 셀 쪽 판정 기록(Calibration 앱)을 정하고, 이 기록은 Fleet 원장이 기계 해제를 받는 조건을 정한다. |
| [D-971](D-971-omx-arm-incidents-in-fleet.md) | 고친다. "해제는 이름 있는 운영자"에 안전한 종류의 기계 해제를 더한다. 원장(`open`→`explained`→`cleared`), 사건 보존, 사람 해제는 그대로다. |
| [D-807](D-807-account-service-credential-ownership-and-acceptance.md) | 따른다. assessor는 `site_users`의 `service` 자격이고 토큰은 `private/`·셀 PC `~/.config/rosy`에만 둔다(D-226). |
| [D-911](D-911-omx-native-reviewed-operating-envelope.md) | 바꾸지 않는다. 해제는 팔을 움직이지 않는다. 다음 세션은 지금처럼 감독 범위 안에서만 연다. |

### 문제

D-1035로 팔 incident 해제를 AI 판정에 맡기기로 했지만, Fleet 해제 경로(`POST .../incidents/{incident_id}/clear`)는 `require_named_operator`만 받아 셀 PC의 기계 자격은 구조적으로 401·403이었다. 기계에 그대로 운영자 권한을 주면 래치·감김·조 끼임처럼 사람이 봐야 할 사건까지 기계가 풀 수 있다.

### 결정

1. **assessor 자격과 팔.** `site_users`의 `role: service` principal 가운데 `ROSY_FLEET_ARM_ASSESSORS`에 팔과 함께 적힌 것만 assessor다. 형식은 `id=source,source;id=source`(예: `cell-a-ai-assessor=omx_arm_a,omx_arm_b,omx_arm_s`)이고 기본값은 비어 있다(설정하지 않으면 기능이 꺼져 있다). 적히지 않은 팔의 사건은 403 `AI_CLEAR_ARM_NOT_ASSIGNED`다.
2. **경로 한정.** assessor는 `POST /api/fleet/workcell-observations/arms/{source_id}/incidents/{incident_id}/clear` 하나만 부른다. 다른 경로는 모두 403 `ARM_ASSESSOR_SCOPE_REQUIRED`다. 이 경로만 자기 guard(`require_incident_clearer`: 이름 있는 운영자 또는 설정된 assessor)를 쓰고 `require_operator`는 바꾸지 않는다.
3. **근거 필수.** assessor 해제는 `note`·`cause`·`basis`가 모두 있어야 한다. 없으면 422 `AI_CLEAR_CAUSE_REQUIRED`다.
4. **종류 게이트(기본 거부).** Fleet은 저장된 측정 사실에 `machine_clearable(facts)`(`core_common.protocol.arm_incidents`, `software_stop` 옆)를 적용한다. `torque_after`(dict)·`latched`(dict)·`windup_hits`(list)·`flagged`(list)가 그 형태로 있어야 한다. 잘린 보고는 목록이 없어 사람 몫이다. 아래 표의 기계 해제 조건을 하나라도 어기면 403 `AI_CLEAR_KIND_REFUSED`다.

   | 사건 종류 | 해제 |
   |---|---|
   | 실행기 표시 행 없음, 그 밖의 조건 모두 충족 | 기계 가능 |
   | 표시 행이 모두 주차 중 부하 정지(`error`가 선택적 `runner: ` 뒤 `^contact in park: [a-z_]+ lag rose to [0-9.]+ units at PWM -?[0-9]+ of [0-9]+`, `caught`·`pushing`·`session ended`·`person_needed` 없음), 그 밖의 조건 모두 충족 (예: 2026-11-17 밤 arm_s `contact in park: shoulder_lift lag rose to 2.2 units at PWM -321 of 600`) | 기계 가능 |
   | 그 밖의 표시 행(조 끼임, `pushing`, `session ended`, 주차 중 조가 덜 닫힘 등)이 하나라도 있음 | 사람 |
   | 래치(`latched`가 빈 dict 아님), 감김(`windup_hits`), 주차 행이 아닌 접촉 정지(`stops`), 모터 고장 기록(`fault_records`) | 사람 |
   | `safe_end`·`folded`가 참이 아님, 토크 미확인 또는 켜짐(`torque_after`가 비었거나 0이 아닌 값), `caps_restored`가 참이 아님 | 사람 |

   주차 중 부하 정지의 예외는 셀 `omx_incident.decide()`가 보류하는 것 가운데 유일하게 기계가 푸는 종류다. 정지 뒤 팔이 스스로 접혀 토크 OFF로 끝났고 다른 신호가 없다는 측정이 근거다. 같은 팔에서 되풀이되면 5항의 하루 한 번 상한이 사람에게 넘긴다.
5. **하루 한 번.** 한 팔의 기계 해제는 원인과 상관없이 24시간에 한 번이다. 두 번째는 403 `AI_CLEAR_REPEAT_LIMIT`이고 사람이 본다. 셈은 현재 설정의 id 목록이 아니라 저장된 표시(`cleared_kind='machine'`)로 한다. 사람 해제는 세지 않는다.
6. **기계 해제 기록.** 기계 해제는 `cleared_by`에 assessor id, `cleared_kind`에 `machine`을 남기고, 라벨 근거는 보낸 값과 상관없이 `unknown`으로 저장한다. 학습은 `repeat`·`measured`만 정답으로 채점하므로 assessor의 원인은 정답 라벨이 되지 않는다. 사건 행의 `cleared.kind`가 `machine` 또는 `person`이다.
7. **사람은 그대로.** 이름 있는 운영자는 지금처럼 모든 종류를 해제한다.
8. **셀 쪽.** `omx_incident.py clear`는 `--token-file` 또는 `ROSY_ARM_ASSESSOR_TOKEN_FILE`로 assessor 토큰을 쓴다. 운영자 토큰 glob(`*-operator-*.token`)과 겹치지 않는다.

### 같은 호스트의 보고자와 assessor

지금은 사실을 보고하는 셀 제어 PC와 assessor 자격이 같은 호스트에 있다. 그 호스트가 오염되면 사실과 해제를 함께 꾸밀 수 있다. 이를 받아들이는 이유는 다음과 같다.
- 셀 PC는 이미 자기 팔을 직접 움직이고 끈다. 해제가 그 이상의 권한을 주지 않는다.
- 해제는 안전한 종류(접힌 안전 종료, 토크 OFF, 아무 신호 없음)로만, 팔마다 하루 한 번으로 묶이고, 기계 해제로 감사 기록에 남는다.

후속: assessor를 AI PC로 옮겨 보고자와 해제자를 나눈다.

### 결과

- 주차 중 부하 정지 뒤 접혀 토크 OFF로 끝난 사건(2026-11-17 밤 arm_s 사례)과 신호 없이 안전하게 끝난 사건은 팔마다 하루 한 번 사람 없이 풀린다. 래치, 감김, 조 끼임, 그 밖의 실행기 표시 행, 접촉 정지, 모터 고장 기록, 접히지 않은 정지, 토크·cap 미확인은 계속 사람이 푼다.
- 판정의 질(프레임·모델)은 D-1035의 셀 쪽 판정 기록이 맡는다. Fleet은 측정 사실, 팔 지정, 하루 한 번 상한으로 거부권만 쥔다.
