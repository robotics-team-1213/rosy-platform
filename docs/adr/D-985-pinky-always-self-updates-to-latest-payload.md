## D-985 접속된 Pinky는 언제나 최신 payload로 스스로 올라간다

**Status:** Accepted (2026-11-07, 사용자 지시: "접속 된 pinky 들이 언제나 github 기준 release 로 해서 자동업데이트가 되도록"). 봉인 기체 포함, OS는 게시만이라는 선택도 같은 날 사용자가 했다.

개정: [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md)의 "봉인된 승인은 hold로 본다"와 "카나리 시한 초과는 철회", [자동 Release 안내](../deployment/pinky-automatic-release.md)의 "frozen OS 파일은 payload를 기다리게 한다".

**Context:** 2026-11-07 접속된 세 대가 10/29 릴리스에 멈춰 있었다. 업데이터는 10분마다 정상으로 돌며 `no newer release`만 답했고, 어느 유닛도 실패로 보이지 않았다. 원인은 서로 맞물린 네 가지였다.

1. 카나리 b8xy의 항법 승인이 현재 릴리스에 묶여 있어 `held`였다. 시한 초과로 004·005가 철회됐고 철회는 기체에서 영구다.
2. 게시 분류는 이미지 경로나 미분류 경로가 하나만 있어도 payload를 보내지 않았다. 비교 기준이 전진하지 않으므로 차이는 쌓이기만 해 저절로 풀리지 않는다. a613 이후 2,429개 경로 가운데 이미지 15개, 미분류 2개(`tools/run_fleet_sim.sh` 같은 개발 도구)가 전체를 막았다.
3. 목록의 기체가 한 대라도 꺼져 있으면 번호 할당과 ABI 검사가 거절됐다.
4. y8xs는 배터리 ADC 오류로 `battery_percent`가 null이라 대상에서 빠졌다. 이 수정은 별도 작업이다.

**Decision:**

1. **로봇에 관련된 변경은 항상 payload로 나간다.** `delivery_policy`는 `none` 또는 `full-payload`만 낸다. `classify_paths`는 사람이 읽는 자문 분류로 그대로 둔다(D-325).
2. **OS Release는 payload 뒤에 게시만 한다.** 마지막 OS Release 이후 frozen OS 입력이 바뀌었으면 payload 전달이 끝난 뒤 게시한다. `canary=[]`, `canary_ok=false`와 BUILD_GO는 그대로라 기체에 설치되지 않는다.
3. **봉인은 자동 hold가 아니다.** payload 업데이터의 `eligibility`와 `precheck`는 승인 표식을 보지 않는다. 승인은 릴리스에 묶여 있어 새 릴리스에서 무효가 되고(`mapping_approval.py check`), 다시 승인하기 전에는 항법이 시작되지 않는다. 시험·주행을 보호하려면 만료가 있는 hold를 명시적으로 건다. OS 설치 쪽(`os_update_policy`)의 봉인 규칙은 바꾸지 않는다.
4. **카나리는 게시 때 고른다.** 설정된 카나리가 지금 적용할 수 있으면 그 기체, 아니면 처음으로 적용할 수 있는 기체다. 아무도 없으면 게시하지 않고 다음 tick까지 기다린다.
5. **시한 초과는 시작 여부로 나눈다.** 마지막 상태가 `idle·staged·waiting·held·ineligible·disabled`면 기체는 이 릴리스를 시작하지 않은 것이다. 철회하지 않고(exit 4) 다음 tick에 다른 유휴 기체로 카나리를 바꿔 다시 서명한다. `applying·stuck·error`나 응답 없음은 릴리스가 기체를 망가뜨렸을 수 있으므로 지금처럼 철회한다.
6. **꺼진 기체는 배달을 막지 않는다.** 번호 할당과 ABI 검사는 응답하는 기체로 한다. 한 대도 응답하지 않으면 거절한다.

7. **표시만 남은 MANUAL은 유휴다.** MANUAL은 마지막 명령 뒤에도 그대로 남는다. 2026-11-07 b8xy·geg6는 조종하는 사람 없이 멈춘 채 이 표시 때문에 갱신되지 않았다. 프로세스 시작, 조종 시도(거절 포함), MANUAL 진입 가운데 가장 최근 것 뒤 10분(`manual_quiet_s`)이 지나면 payload 업데이터는 유휴로 본다. 값을 모르면 계속 막고, 정지·활동·E-Stop·배터리·hold 검사는 그대로다. OS 설치는 계속 IDLE을 요구한다.

**유지하는 것:** 서명 검증, 유휴·배터리·명시 hold·claim 조건, 건강 검사와 자동 롤백, 카나리 commit 뒤 나머지 진행, 롤백·거절 시 철회, 서명 키를 운영 PC에만 두는 것.

**Consequences:**

- 항법 승인을 받은 기체도 새 릴리스가 나오면 유휴 때 갱신되어 항법이 멈추고 재승인이 필요하다. 승인 주행을 앞두면 hold를 건다.
- 새 payload가 옛 OS와 맞지 않으면 기체의 건강 검사가 롤백하고 그 id를 실패로 기록한다. Python 런타임이 다르면 `image_required`로 거절하고 카나리 단계에서 바로 철회한다. 어느 쪽이든 OS 설치가 필요하고 이는 사람 결정이다.
- 분류되지 않은 경로만 바뀐 main도 payload를 한 번 더 만든다. 개발 도구만 바뀌어도 기체가 재시작될 수 있는 비용을 멈추지 않는 쪽과 맞바꾼 것이다.
- 시한 직전에 응답이 없던 카나리는 꺼진 것과 망가진 것을 구별하지 못해 철회한다. 안전 쪽 선택이고, 다음 main이 새 Release로 메운다.
- `os_published_sha`가 없는 새 설치는 OS 비교 기준이 없어 OS를 게시하지 않는다. 지금 운영 상태에는 값이 있다.
- 게시는 여전히 운영 노트북의 예약 작업이 한다(D-412). 노트북이 꺼져 있으면 새 Release가 나오지 않고, 이미 나온 Release 설치는 기체가 스스로 계속한다.

**기각:** 재승인 자동화(사람의 항법 승인을 없앤다), 카나리 없이 전 기체 동시 적용(깨진 릴리스가 함대 전체로 간다), OS 자동 설치(BUILD_GO·G4 수용 전).

### 부록 2026-11-09: 강제 갱신 (`-ForceUpdate`)

운영자가 "이 서명 릴리스를 지금 이 기체에 올려라"를 명시할 수 있다. 정본은 이 절이고 런북과 스킬 카드는 여기를 링크한다.

```powershell
deployobot\pinky_proosy-release-push.ps1 -Robot <robot> -Tarball <id>.tar.gz -ForceUpdate -ExpectReleaseId <id> -Reason "<이유>"
```

- **우회하는 것:** 기체 updater의 정책 상태, 곧 롤아웃 wave 지연, canary 순서, 그 id의 withdrawn·failed 기록. 수동 push는 updater를 거치지 않으므로 이 기록은 읽히지 않고, 기체가 그 id로 올라오면 `current`가 되어 더는 후보가 아니다. 기체 쪽 새 코드가 필요 없어 2026.10.29 이미지의 updater에서도 같다.
- **우회하지 않는 것:** 서명 검증(PC와 기체), claim, 보정 세션 가드(`-Force`는 별개의 기존 스위치), 건강 검사와 자동 롤백, 그리고 기체 `rosy_auto_update.py precheck`가 보는 명시 hold, 다른 claim, CORE 정지 상태(MANUAL-quiet), 배터리 40% 이상 또는 충전, 상태 입력 신선도. hold는 먼저 `release-hold`로 푼다.
- **precheck 시점:** 업로드·unpack 뒤 활성화 바로 앞이다. push 자신의 claim 사유만 걸러내고 다른 사유가 하나라도 있으면 아무것도 바꾸지 않고 사유를 보이며 멈춘다. precheck를 실행할 수 없는 기체(updater 없음)는 idle·배터리·hold를 확인할 수 없으므로 **거절**한다. 그 경우 사람이 직접 확인한 뒤 `-ForceUpdate` 없이 push한다.
- **필수 입력:** `-ExpectReleaseId`(패키지의 id와 같아야 함)와 `-Reason`. `-Rollback`과는 함께 쓰지 못한다.
- **기록:** `$ROSY_SCRATCH/rosy-rollout-evidence/<날짜>/rollout.jsonl`에 `event=force_update`로 요청(`requested`)과 결과(`installed`·`failed`)를 누가·언제·어느 릴리스·왜와 함께 남긴다. IP는 `<ip>`로 대체한다.

기각: updater에 `apply-now` 명령 추가(10.29 기체에 닿지 않고, 안전 검사를 한 벌 더 만든다), withdrawn 기록을 지우는 명령(위 이유로 필요 없다).

