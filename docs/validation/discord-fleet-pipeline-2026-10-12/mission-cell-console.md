# Discord Mission·Cell Console source 검증

2026-10-12. Branch `feat/discord-workflow`. 통합 source `48d3aa835fc3d8723fc98a8493665bf4fef86490`, main `4dc5229869ab716e7f1e34b6404426ea95f8c277` 포함.

Console는 Discord 원문을 확인한 뒤 현재 사용자 소유의 기존 일반 Mission 후보를 준비하고 별도 확인창에서 기존 admission을 호출한다. Cell 링크는 기존 recipe/cell 편집·저장·compile 화면을 재사용하며 source service author와 기명 독립 approver를 보존한다. 문서·digest·현재 요청 관계를 서버에서 확인하고 새 writer/rearm/provider를 만들지 않는다.

## 증거

로그 root: `X:/DevTemp/projects/rosy-platform/2026-10-12--010335--discord-fleet-pipeline--1dc770/logs/`.

| Source / 로그 | 실제 terminal 결과 | 범위 |
|---|---|---|
| `a791c3cce` / workflow-mission-browser-red | 2 NEW, 6 PASS | Mission picker 미구현 RED |
| `827d5750c` / workflow-mission-browser-green | 8 PASS / NEW0 | Chromium 1366/320, 원문·owned source·prepare, 별도 admission 취소/확인, 기존 작업 목록 |
| `827d5750c` / workflow-owned-mission-green | 16 PASS / NEW0 | 기존 실제 owner/SQLite source 복사·owner/scope·독립 승인 |
| `3ece93ecf` / workflow-lineage-red | 11 NEW | source fence/supersedes 및 nonready 상태가 ordinary Mission으로 복사되는 결함 재현 |
| `8fc6a0cd0` / workflow-lineage-green | 52 PASS / NEW0 | feedback source 거절, 기존 Mission/Cell·Task workflow 경계 |
| `8fc6a0cd0` / workflow-cell-browser-regression | 53 PASS / NEW0 | 실제 Chromium 기존 Cell 전체와 Discord scope 1440/390/320; compile→prepare→취소/별도 승인·XSS·overflow |
| `48d3aa835f` / workflow-main-owner-integration | 109 PASS / NEW0 | 최신 main 통합 후 Mission/Cell owner/API/Task workflow/GLM config 회귀 |

각 terminal 로그를 `test/known_failures.py`로 분류했다. RED의 NEW를 기존 실패 목록에 넣지 않았다. Cell53은 runner의 reachable-host fallback이며 지연·용량 수용이 아니다. 통합109는 AI PC 자원 하한 충족. 실제 브라우저는 테스트 API/SQLite·가짜 장치를 쓰며 운영 Console/Discord/장치 수용을 대신하지 않는다.

Source 복사는 PROPOSED/RESOLVED이며 source lineage/supersedes가 없는 일반 후보만 허용한다. `source_dispatch_generation=0`, `source_event_watermark=0`도 nonnull로 거절하며 모든 거절 시험에서 원본 proposal 하나, 새 Mission0, 관계 REQUESTED, resource claims0을 확인했다. 모델 feedback/replan 소유자의 fence를 없애는 복사를 허용하지 않는다.

## 검토와 남은 gate

독립 safety_structure_review는 `8fc6a0cd0` source/Safety를 승인했다. 당시 Fleet 실측54,500은 기존54,214+150을136줄 초과했다. 구조 PASS로 표시하지 않았다. 통합 main의 별도 책임 추출·설치 격리·기존 +150/파일 상한/추출 의무를 유지하며 위험 사건 구현 후 최종 부모 재판정이 필요하다. 통합 lint 0 errors / 기존 last_verified warnings28.

D-693의 현재 사건 인수 연결은 ADR 계약만 준비했으며 구현·시험은 후속이다. 최신 전체 영향 검사, local FF, CI·서명 배포, 비공개 Fleet 설정 활성화와 실제 Discord 원문→Console→원장→원래 메시지 회신 readback이 남는다. push·운영 발송·provider·로봇 명령은 실행하지 않았다. 오프라인 로봇 FIELD는 별도 gate다.
