# Fleet 팀 알림·사람 인수 책임 분리

날짜: 2026-10-11. 결정: [D-661](../adr/D-661-fleet-named-handoff-and-team-notification-outbox.md),
[책임 분리 실행 계획](2026-10-11-responsibility-authority-orchestration.md).

최종 원격 구조 검사는 Fleet 52292줄로 기존 52083+150 한계를 넘었다.
새 두 모듈의 소유자는 사건 판단·자동 해결기가 아니라 팀 통지·이름 있는 담당 인수다.
두 모듈을 실제 `fleet/incidents` 하위 패키지로 묶고 독립 크기 단위로 측정한다.
예산·허용 증가량과 기존 observe/server/UI 분리 의무는 유지한다.

| 기존 | 분리 후 | 소유 책임 |
|---|---|---|
| `fleet/incident_handoff.py` | `fleet/incidents/handoff.py` | 현재 사건·의미 revision에 묶인 이름 있는 사람 claim |
| `fleet/notifications.py` | `fleet/incidents/notifications.py` | 기존 DB의 outbox·고정 채널 전송·receipt |

기능을 그대로 이동하고 직접 import만 갱신한다. shim·새 프로세스·추가 DB·명령 경로는 없다.
현재 판단·관측 종료 원장은 `stuck/reports.py`, 자동 해결은 `stuck/resolver.py`,
인증·동시성 fence·앱 worker 생명주기는 기존 서버 소유자에 남는다.
두 모듈은 기존 원장 연결을 주입받고 서버나 해결기를 import하지 않는다.

호출자는 CLI, 앱 조립부, Console 라우트, 사건 원장, 두 시험과 wheel/sdist 설치 검사다.
`find_packages`가 새 패키지를 배포하며 source/native/Docker 경로는 같은 Fleet tree를 사용한다.
전체 호출자와 설치 검사를 함께 갱신하고 이전 import 경로를 남기지 않는다.

순서: 직접 이동·호출자 갱신 → 독립 경계 검토 → Fleet 부모/하위 단위 측정 →
원격 구조·알림·인수·설치 시험 → known failures NEW0 확인 → 로컬 FF 착지.
정상 비개입의 zero-send, 전송 직전 case/claim/expiry 검사, claim 경쟁·재시작,
전송 불명·부분 실패·secret 비노출 시험은 기존 의미를 유지한다.

독립 검토자 `responsibility_review`는 2026-10-11 경계와 독립 단위 등록을 확인했다.
분리 직후 독립 실측은 부모 51933줄, incidents 360줄이다. 최종 영향군493 passed/NEW0와
`7afb0e2c4f` 로컬 FF를 확인했다. 실제 측정과 원격 terminal
증거는 [착지 기록](../validation/responsibility-boundaries-2026-10-11/landing.md)에 남긴다.
다음 통지/사람 인수 성장도 이 경계에서 재검토하며 판단이나 실행 권한을 가져오지 않는다.
실제 채널/현장 수용과 제한 모델 토론은 기존 HOLD를 유지한다.
