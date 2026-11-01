# GitHub merge queue 하루 시범 (D-905, 2026-10-28)

D-905(Proposed)의 하루 시범 기록이다. 사용자 지시로 2026-10-28 15시경 시작했다. 결과는 시범이 끝나면 이 파일에 더한다.

## 설정

- 저장소 ruleset `main-protection`에 `merge_queue` 규칙을 더했다: merge 방식 MERGE, 그룹 최대 4개, 최소 1개, 최소 대기 2분, 검사 응답 한도 90분, ALLGREEN. 필수 검사 `ci-result`, merge commit 전용, force-push·삭제 금지는 그대로다.
- 저장소 설정 "Allow auto-merge"를 켰다(검사가 끝나기 전에 큐에 넣기 위해).
- `ci.yml`은 이미 `merge_group`을 받는다. 병합 그룹은 늘 풀 티어를 돈다.
- 되돌림: 규칙을 이 시범 전 상태로 돌리고(`merge_queue` 규칙 삭제) auto-merge를 끈다.

## 시범 PR

| PR | 내용 | 큐 넣음 |
|---|---|---|
| #214 | land가 ERROR 줄을 실패 증거로 보고, 증거 없는 exit 1은 한 번 다시 돈다. 격리 게이트는 격리 목록을 NEW로 세지 않는다 | 15:20 |
| #215 | `land.py --urgent` 급한 표 | 15:26 |
| 이 PR | 시범 기록 | — |

브랜치는 모두 `origin/main`(4906e5a81a)에서 갈랐다. 로컬 main에서 가르면 아직 게시하지 않은 커밋이 같이 올라간다. 이 저장소는 `rosy.publishOnly`로 주제 브랜치 push를 막으므로 `ROSY_PUSH_REASON`에 시범 사유를 적어 push했다. push 전에 범위의 커밋별 비밀 검사(`publish_main.py --secret-scan`)를 돌렸다.

## 잴 것

- PR 열기 → 큐 넣음 → 그룹 CI 시작 → 병합 시각, 그룹 CI 시간
- 그룹 실패와 재시도, CI 컨테이너 전용 실패 건수
- 같은 시간대 로컬 main 착지(대기열 진입 → 착지)와 비교
- 성공 기준(D-905): 큐 진입 → 병합 p50 30분 이하, 환경 차이로만 생긴 실패 0, 비밀 검사 누락 0
