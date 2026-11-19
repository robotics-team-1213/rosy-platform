## D-1055 PR + Merge Queue를 유일한 병합 경로로 하고 land.py 착지를 은퇴한다

**Status:** Proposed (2026-11-20, 사용자 결정 "지금 바로": 착지 GitHub 이관·경량화. 은퇴는 아래 기준 충족 뒤 Accepted로 바꾼다)

잇는 결정: [D-868](D-868-local-main-first-merge-commit-publish.md)(로컬 main 우선, 이 ADR이 개정한다) · [D-762](D-762-main-gateway-pull-request-merge-queue.md)(Merge Queue) · [D-1052](D-1052-self-review-and-zero-full-ci.md)(Zero-FULL, 2-레인 공존) · [D-803](D-803-landing-queue-before-delta-rerun.md)(착지 대기열) · [D-441](D-441-site-stack-automatic-update.md)(정확 SHA `ci-result` 서명).

### Context

1. 노트북에서 `land_async.py` 감독·tick·rollup 프로세스가 상주한다. 메모리 부족 때 유휴 셸 감시가 조용히 죽고, 재시작 뒤에도 고아 착지가 남아 되살림 루프가 또 프로세스를 띄운다. 착지 한 건이 노트북 자원과 세션 생존에 묶인다.
2. 측정한 지연(2026-11-20 패널 판정, 조정 robot-d4): 로컬 착지 요청→공개 main은 게시 포함 p50 4~5 h, p90 7~13 h(추정). 로컬 착지만 보면 p50 1.9 h, p90 12.8 h.
3. 그대로 GitHub로 옮기면 더 느려질 수 있다. 변경 하나가 PR CI·merge_group CI·push CI를 각각 19~27분 돌고, 한 실행이 약 30잡이라 무료 플랜 동시 20잡에서 피크 때 적체한다(가정: 하루 30건이 러너 용량 94%, 60건이 188%). 이관과 경량화는 한 세트다.
4. D-868의 게시 PR은 로컬 main 전체를 한 번에 올려 PR 하나가 거대 diff를 담는다(scope 약 26분).

### Decision

1. **유일한 병합 경로:** 공개 `main`으로 가는 변경은 주제 PR 하나가 Merge Queue를 거쳐서만 들어간다. `tools/pr_land.py`가 push와 auto-merge를 걸고 곧 끝나며, 노트북에 상주 프로세스를 남기지 않는다. 실험실 세션도 같다.
2. **land.py 착지 은퇴:** `tools/land.py`·`land_async.py` 착지와 로컬 main 우선 게시 체인(D-868)은 아래 은퇴 기준을 채우면 끈다. 은퇴 전에는 D-1052의 2-레인 공존을 유지하고, 새 상주 프로세스는 만들지 않는다.
3. **경량화(전환과 한 세트, 시험은 약화하지 않는다):**
   1. D-1052 affected 캡슐 실측과 앱 소유 기준 정밀화(작은 변경 2~5잡, unknown→FULL·안전·필수 ID 유지).
   2. 작은 토픽 PR로 게시 거대 diff 제거.
   3. GHCR 프리빌트 CI 이미지(apt·pip 제거, apt 미러 장애 제거).
   4. 순수 문서·기록 변경은 build-smoke 생략, 문서 계약 검사만(기록 소비자 시험 유지).
   5. 실험실 증거를 PR 필수 상태 체크로 승격(PR CI와 병렬), 일치할 때만 merge_group이 재사용한다.
4. **전환(두 레인):** 은퇴 기준을 채울 때까지 레인 둘이 공존한다. 공용 클론은 D-868 레인, 토픽 PR은 이 ADR의 레인이다. 5번(실험실 증거 상태 체크) 전에는 현재 `pr_land` 가드가 GitHub UI 직접 병합을 못 막으므로 전면 전환하지 않는다.
5. **은퇴 기준(모두 충족, 영업일 2일 연속 관측):**
   - 요청→병합 p50 ≤ 30분.
   - 큐 대기 p90 ≤ 40분.
   - CI 실행 p90 ≤ 10분.
   - 시험 없는 병합 0건.
   - skip-녹색(시험이 건너뛰어졌는데 녹색) 0건.
   - 공용 클론의 로컬 병합 0건.
   - 서명된 배포 2회 연속 성공.
6. **반증 조건(전환 확대 중지):** 토픽 PR 녹색 CI p50 > 12분 또는 평균 > 8잡, scope p50 > 3분, 실험실 표면 무증거 병합 1건 이상, 요청→병합 p50 > 30분.
7. **실험실 증거 규칙:** 실험실 전용 표면(OMX adapter, browser, `host_alone`, `LAB_ONLY`, safety)을 바꾸는 PR은 `remote_pytest`·`land_cache` 증거가 같은 SHA와 일치해야 병합한다. 증거는 필수 상태 체크로 걸고, 없으면 병합을 막는다. self-hosted runner는 두지 않는다(공개 저장소, D-437).

### D-868 개정

- D-868 1·2항(로컬 main 먼저 착지, 로컬 main 전체를 publish 브랜치로 게시)은 은퇴 기준을 채운 날 대체된다. 그때 D-868 Status를 `Superseded by D-1055`로 바꾼다. 그 전에는 유효하다.
- D-868 3·4항(merge commit만 허용, force-push 금지, 원래 커밋과 `Safety-Review:` trailer 보존)은 유지한다. 주제 PR도 merge commit으로 병합하며 squash와 rebase는 쓰지 않는다.
- D-868이 푼 문제(로컬 main과 origin/main 이력 분기)는 로컬 main을 없애서 푼다. 주제 브랜치는 `origin/main`에서 만든다(D-868 1항의 반대).

### Consequences

- 노트북 상주 프로세스가 0이 되어 메모리 사고의 근본 원인이 사라진다.
- 기대(추정): 요청→공개 main p50 15~30분, p90 45~100분. 실측으로 확인하며, 맞지 않으면 6항에 따라 중지한다.
- 한동안 두 레인을 유지하는 비용이 든다. 시연 전에는 workflows·ruleset을 바꾸지 않는다.

### 확인하지 못한 것

- 실제 러너 동시성 상한, 잡별 실측 합계, 실험실 표면 변경 비율.
- PR에서 정적 검사만 하고 큐에서만 전체 pytest를 도는 안은 보류했다(큐 탈락·재진입 증가). 경량화 1~5 뒤에도 수요가 넘치면 다시 본다.
