# 책임 분리 구현과 팀 인수 기록

브랜치: `refactor/responsibility-execution`. 착수 소스 `51ad9b355f`; [착수 소유 목록](result.md)은 당시 소스를 보존한다. 아래는 후속 구현 증거이며 실제 현장 수용 기록이 아니다.

| 단계 | 실제 소유 경로·변경 | 원격 terminal 증거 |
|---|---|---|
| 1 | Fleet `server/model_feedback_dispatch.py`로 원장 dispatcher 이동; Decision에는 모델 계약/catalog 유지 | `7822c3860`, tools-green: 114 passed, NEW0 |
| 2 | `rosy.execution.site.goal_evidence`와 `workflow`에 순수 계산; Fleet store/auth/admission 유지; wheel/sdist·Docker source closure·native installer 호출자 갱신 | execution-green-4: 147 passed, NEW0 |
| 3 | D-660 현재 판단/만료/종료 근거와 읽기 API; 당시 상태·자연 해소·조치 미확인 표시 | `b196ab2aa`, judgment-green: 99 passed, NEW0; Node 22 passed |
| 3/4 | D-661 이름 있는 owner claim, case/revision/freshness 경쟁 검사, resolver·명령과 직렬화, 재시작 인수 복원 | `30d994bdb`, handoff-green-2: 127 passed, NEW0 |
| 4 | 기존 Fleet DB에 알림 outbox; Discord/Slack/Telegram fixed destination; 기본 OFF; 종료/인수/만료 직전 guard·부분 실패·UNKNOWN·secret 비노출 | `6458e94eb0`, notifications-green-3-retry: 149 passed, NEW0 |
| 통합 | 팀 통지·사람 인수 `fleet/incidents` 분리, 최신 main 순수 진척·지연 schema import와 설치 보호 검사의 통합 | `7afb0e2c4f`, 최종 영향군493 passed/NEW0; 로컬 FF 완료, push 없음; [착지 증거](landing.md) |
| 5 | D-662 기존 learning 평가 holder에 독립 offline checker; 검수/한계 미정 HOLD, 물리 split/hash, P/N/ABSTAIN/자연 해소/위험 평가 | `bf71282cc5`, acceptance-green: 12 passed, NEW0; 검토 보강 후 최종 결과는 착지 기록 |
| 6 | 기존 D-640 모델 런 계획의 dispatcher 경로 갱신 | 0~5 실제 수용 대기 HOLD; 구현/실제 provider 호출 없음 |

로그 기준: `X:/DevTemp/projects/rosy-platform/2026-10-11--201913--responsibility-execution--256063/logs/`. 각 GREEN terminal을 `test/known_failures.py`와 비교했다. 설치 증거는 원격 x86 wheel/sdist/source 구성/native fake이며 실제 ARM64 이미지 빌드나 장치 배포가 아니다. 예상 RED와 수정 전 실패는 baseline에 넣지 않았다. 알림 green-3 첫 시도는 SSH 운송 실패였으며 별도 retry에서 terminal을 확인했다.

판단은 읽기 shadow이고 `action_admissible=false`다. CORE/OMX 최종 실행 writer, 기존 Mission transaction/claim/generation fence를 유지한다. 알림 수락·수신·담당 인수·목표 관측·사건 종료를 별도 기록한다. 자연 해소와 관측 종료는 조치 성공이 아니다. 최종 HTTP 진입 뒤 이미 전송 중인 알림을 회수할 수는 없다.

팀은 새 Discord 서버/채널과 비공개 설정을 준비하고 Pinky 차선 정지·재관측 정답을 독립 검수한다. [채널 인수 절차](../../reference/team-discord-incidents.md), [평가 검수 절차](../pinky-judgment-acceptance-2026-10-11/review.md), [단계별 계획](../../plans/2026-10-11-responsibility-authority-orchestration.md)을 따른다. 인명/계정/웹훅 값을 문서나 채팅에 요청하지 않는다.

독립 검토에서 필수 ABSTAIN 오판과 동일 물리 구간 복제의 통과 가능성을 발견했다. 각각 RED6/RED1 NEW를 기록한 뒤 `0b14fa02b0`에서 사전 검수 한계와 물리 중복 거절을 추가했다. acceptance-review-green에서 checker 8건과 wheel/sdist/source 설치 3건, 총 11 passed/NEW0를 확인했다. 별도 검토자는 두 결함 및 알림 OPEN/CLOSED 만료 수정의 해소를 확인했다.

실제 채널 발송→수신→Console 로그인→담당 인수 readback→현장 결과→종료 통지와 독립 정답/허용 한계의 receipt는 없다. CI/push·배포·provider 활성화·실물 motion을 수행하지 않았다. 단계 3~5 운영 수용과 단계 6은 HOLD다. 최종 최신 main 통합/원격 시험/로컬 FF 결과는 별도 `landing.md`에 기록한다.
