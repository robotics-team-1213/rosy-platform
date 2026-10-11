# Console 검토와 기존 Task 관계 검증

Branch: `feat/discord-workflow`. Tested source: `f26b367324`. 후속 `8b5d5058e0`은 AST가 같은 공백 정리다.

원격 AI PC의 관련 시험 67건 PASS, exit 0, known_failures NEW 0. 로그는 X의 기존 discord-fleet-pipeline 세션 `logs/workflow-routes-green/run-1.txt`다. 해당 실행은 자원 floor를 통과했다. 첫 workflow 시험은 필수 evidence 인수를 빠뜨린 fixture 오류 5건을 발견했고 None을 명시해 수정했다. 기존 실패 목록은 변경하지 않았다.

새 `ChannelWorkflow`는 접수 원문 hash·현재 기명 owner·검토 revision을 확인하고 READY/HOLD/REJECTED와 기존 주행 Task 관계를 tasks DB에 저장한다. Task 연결은 기존 operator source·actor·idempotency key·robot·navigate goal을 모두 확인한다. 다른 owner는404/403, stale/hash/provenance 충돌은409다. Task 원장을 읽어 UNKNOWN 등 현재 상태를 반환하고 작업을 생성하거나 장치에 요청하지 않는다.

API reference v1.211, strict 공통 DTO, CORE API metadata 및 기존 계약 버전 pin을 함께 갱신했다. WS protocol_version 1.0과 기존 Task/Mission/Cell Job 실행·승인 규약은 유지한다. HTTP 경계 시험은 principal 주입·bool revision·잘못된 후보 scope·빈 reason·bool 좌표를 mutation 전에 거절하는지 확인했다. 변경된 workflow/DTO/시험 flake8 0 errors.

아직 Console의 실제 확인·제출 UI, Mission/Cell Job 관계 어댑터, 작업 결과 outbox, 위험 사건 경로, installed closure·size/독립 검토, 최신 main 착지, CI·서명 배포와 실제 Discord 왕복은 미완료다. source HTTP 시험은 실제 운영 수용을 대체하지 않는다. 운영 채널 전송·로봇 명령은 없다.
