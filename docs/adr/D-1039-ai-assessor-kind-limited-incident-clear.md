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

1. **assessor 자격.** `site_users`의 `role: service` principal 가운데 `ROSY_FLEET_ARM_ASSESSORS`(쉼표 목록, 기본 `cell-a-ai-assessor`)에 든 것만 assessor다. assessor는 `POST /api/fleet/workcell-observations/arms/{source_id}/incidents/{incident_id}/clear` 하나만 부른다. 다른 경로는 모두 403 `ARM_ASSESSOR_SCOPE_REQUIRED`다(`auto-track-calibration`과 같은 경로 한정 예외).
2. **근거 필수.** assessor 해제는 `note`·`cause`·`basis`가 모두 있어야 한다. 없으면 422 `AI_CLEAR_CAUSE_REQUIRED`다. `cleared_by`에 assessor id가 남는다.
3. **종류 게이트.** Fleet은 저장된 측정 사실에 `machine_clearable(facts)`(`core_common.protocol.arm_incidents`, `software_stop` 옆)를 적용한다. 허용은 `safe_end`·`folded`가 참이고, `torque_after`가 비어 있지 않으며 모든 모터가 0(OFF)이고, `latched`·`windup_hits`가 비어 있고, `flagged`에 `caught`가 없을 때뿐이다. 읽을 수 없거나 `truncated`인 사실도 사람 몫이다. 아니면 403 `AI_CLEAR_KIND_REFUSED`다.
4. **반복 상한.** 같은 팔에서 assessor가 같은 `cause`로 24시간 안에 이미 해제했으면 403 `AI_CLEAR_REPEAT_LIMIT`다. 사람 해제는 세지 않는다. 같은 원인이 되풀이되면 사람이 본다.
5. **사람은 그대로.** 이름 있는 운영자는 지금처럼 모든 종류를 해제한다.
6. **셀 쪽.** `omx_incident.py clear`는 `--token-file` 또는 `ROSY_ARM_ASSESSOR_TOKEN_FILE`로 assessor 토큰을 쓴다. 운영자 토큰 glob(`*-operator-*.token`)과 겹치지 않는다.

### 결과

- 접힌 채 토크 OFF로 끝난 보호 정지(예: 2026-11-17 밤 `contact in park: shoulder_lift lag`)는 사람 없이 풀린다.
- 래치, 감김, 조 끼임, 접히지 않은 정지, 토크 미확인은 계속 사람이 푼다.
- 판정의 질(프레임·모델)은 D-1035의 셀 쪽 판정 기록이 맡는다. Fleet은 측정 사실과 반복 상한으로 거부권만 쥔다.
