# Console 검토와 기존 Task 관계 검증

Independent read-only review approved product source `a4a3ad4a0` (HEAD `30e9fe85a` only adds evidence). No important source/Safety blocker remains. Reviewer directly measured Fleet parent 54,214 = Fleet 35,511 + Decision 1,658 + Console 16,800 + Discord 245. The limited re-verdict preserves +150, every file ceiling/hard tier and full-progress/observe/server/UI extraction obligations; future Mission/Cell/incident additions require separate review. app.py 906, TaskStore 1035/1060 and Console 1031/1175 satisfy their existing ceilings. Remote 187 and Chromium 6 passes are supplied execution evidence, not tests run by the reviewer. Latest HEAD, signed CI deployment and actual Discord round-trip acceptance remain separate gates.

## Fleet lifespan integration and current Console result

`305ac3e19`: remote AI PC 83 PASS / NEW 0, including Gateway, replies, durable outbox and architecture size guards. Log: existing X session `logs/workflow-lifespan-roundtrip/run-1.txt`. The opt-in lifespan test uses actual Gateway dispatch, Fleet reception journal, worker and DiscordReplies with MockTransport; duplicate intake sends once, verified response persists SENT, shutdown cancels workers and leaks no task. Default-OFF and startup-failure tests remain. This proves source wiring, not real Discord delivery.

`586c99927` Chromium RED: two viewport cases retained QUEUED after the existing work refresh even when the ledger response became COMPLETED. Classified 2 NEW; no known-failure allowlist change. `bd6bd4730` fixes this through the current request view: only LINKED reviews reload, current selection/lifetime are checked, pending operator drafts are preserved. Remote AI PC Chromium 6 PASS / NEW 0 at 320/1366 widths; no device or external message was sent. Logs: `logs/workflow-live-result-red/run-1.txt` and `logs/workflow-live-result-green/run-1.txt`. New UI source is undergoing independent review; signed deployment and real user-request/result readback remain unfinished.

Independent read-only follow-up approved `bd6bd4730` source/Safety without important blockers. Measured parent 54,227 = Fleet 35,511 + Decision 1,658 + Console 16,813 + Discord 245, +13 within the unchanged 54,214 verdict allowance. app906/TaskStore1035/Console1031 ceilings remain; channel view102/work view142. The reviewer confirmed LINKED-only reads, stale-response protection and preserved READY drafts; the supplied terminal Chromium GREEN above closes the previously pending browser check. No Mission/Cell/incident or production acceptance is included. Harness lint: 0 errors / 28 existing last_verified warnings; no baselines were promoted using partial tests.

Branch: `feat/discord-workflow`. Tested source: `f26b367324`. 후속 `8b5d5058e0`은 AST가 같은 공백 정리다.

원격 AI PC의 관련 시험 67건 PASS, exit 0, known_failures NEW 0. 로그는 X의 기존 discord-fleet-pipeline 세션 `logs/workflow-routes-green/run-1.txt`다. 해당 실행은 자원 floor를 통과했다. 첫 workflow 시험은 필수 evidence 인수를 빠뜨린 fixture 오류 5건을 발견했고 None을 명시해 수정했다. 기존 실패 목록은 변경하지 않았다.

새 `ChannelWorkflow`는 접수 원문 hash·현재 기명 owner·검토 revision을 확인하고 READY/HOLD/REJECTED와 기존 주행 Task 관계를 tasks DB에 저장한다. Task 연결은 기존 operator source·actor·idempotency key·robot·navigate goal을 모두 확인한다. 다른 owner는404/403, stale/hash/provenance 충돌은409다. Task 원장을 읽어 UNKNOWN 등 현재 상태를 반환하고 작업을 생성하거나 장치에 요청하지 않는다.

API reference v1.211, strict 공통 DTO, CORE API metadata 및 기존 계약 버전 pin을 함께 갱신했다. WS protocol_version 1.0과 기존 Task/Mission/Cell Job 실행·승인 규약은 유지한다. HTTP 경계 시험은 principal 주입·bool revision·잘못된 후보 scope·빈 reason·bool 좌표를 mutation 전에 거절하는지 확인했다. 변경된 workflow/DTO/시험 flake8 0 errors.

## Console와 결과 회신 후속

Source `3861935d44147866301c1db42448d26e52973418`의 관련 Gateway·workflow·reply·intake·문서 경계·wheel/sdist·secret 검사 192건 PASS, exit 0, NEW 0. 로그: 기존 X 세션 `logs/workflow-source-final/run-1.txt`. 이 실행은 원격 자원 floor 아래 fallback이었으므로 자원 수용 증거로 사용하지 않는다. 기존 실패 목록 변경 없음.

실제 Chromium `b45e54d05a`에서 320/1366 화면과 viewer/operator 기존 목록을 포함한 6건 PASS, NEW 0. 로그: `logs/workflow-browser-submit-2/run-1.txt`. Site PC floor 통과(8.8 GB). 요청 원문은 textContent이며 기명 owner의 검토만 표시한다. 보류/후보 저장에는 장치 요청이 없고 확인창 취소에도 POST가 없다. 명시 확인 후 기존 Fleet goal API의 고정 request key와 Task ID로 관계를 저장한다. LINKED에는 재제출 버튼을 숨긴다. 확인·제출은 fake API 기반이며 실제 로봇 명령을 보내지 않았다.

검토 상태와 회신 intent는 같은 SQLite commit이다. Task 결과 관찰은 기존 원장을 읽고 COMPLETED/FAILED/HOLD/CANCELED/EXPIRED/UNKNOWN 상태마다 원래 메시지에 한 번만 회신 intent를 만든다. 장치 실행 상태를 새로 쓰지 않는다. UNKNOWN은 결과 미확인이며 완료로 승격하지 않는다. 접수/검토 원문과 임의 사유를 Discord 회신에 복사하지 않는다. 전송 opt-in은 기존 설정의 기본 false를 유지한다. reply client 초기화 실패의 Gateway 누수 회귀를 RED로 확인하고 lifecycle finally에서 취소하도록 수정했다.

새 UI owner `channel-request-view.js`를 기존 Console allowlist와 wheel/sdist asset 목록에 등록했다. 패키지 시험의 70개 고정 수가 새 71개 실제 자산과 충돌한 RED를 수정하고 전체 해시 readback을 통과했다. 최신 main의 GLM 경로 변수명 오거절은 값이나 검사 정책을 바꾸지 않는 이름 정리로 해결하고 GLM/비밀 경계 시험도 통과했다.

Mission/Cell Job 관계 어댑터, 위험 사건 경로, 실제 opt-in lifespan 전송 통합 시험, size/독립 검토, 최신 main 착지, CI·서명 배포와 실제 Discord 왕복은 미완료다. source HTTP·Chromium 시험은 실제 운영 수용을 대체하지 않는다. 운영 채널 전송·로봇 명령은 없다.

## 독립 검토 후 보강

독립 검토는 기존 두 단계 goal→link 흐름의 stale READY/HOLD 경쟁과 새 Task 결과 회신의 과거 owner mapping 누락을 발견해 승인을 보류했다. 위 192/6 PASS는 이 문제를 검증한 증거가 아니며 운영 허용에 사용하지 않는다. 당시 Fleet parent 실측54,137은 기존53,606 대비+531로 제한 재판정도 필요하다. +150와 파일 상한·기존 추출 의무는 완화하지 않는다.

- Owner scope RED3 → source `99790900f8` 관련45 PASS/NEW0, AI PC floor 통과. 원래 receipt의 user/owner/guild/channel을 새 회신 생성·claim·발송 직전에 다시 검사한다. mapping 교체/삭제·channel 교체 후 재시작해도 폐기된 요청에는 새 결과 회신을 만들지 않는다.
- Atomic admission RED3 → source `4919e4627b` 관련49 PASS/NEW0. 기존 TaskStore 생성 트랜잭션에 현재 owner/hash/revision/READY/candidate 검사와 LINKED 예약을 함께 둔다. 다른 탭에서 HOLD 또는 다른 goal로 바꾸면 Task 생성이0이며, 같은 확인 revision 재시도는 같은 기존 Task다. 이 실행의 원격 자원 fallback을 성능 수용으로 사용하지 않는다.
- API v1.212 및 Console source `49490991a8`은 `/channel-requests/{id}/submit`에 expected_hash/revision만 보낸다. server의 기존 FleetTaskService가 기존 actor/key/queue/fence를 유지한다. 새로운 writer나 dispatch 활성화가 없다. 원격 영향군과 실제 Chromium의 새 SHA 최종 회귀는 진행 중이며 재검토도 요청했다.

Source `a59638b7bb` 최종 관련187 PASS/NEW0, Model PC floor 통과. `49490991a8` atomic Console Chromium6 PASS/NEW0(자원 fallback이므로 성능 증거 아님). 로그는 각각 `logs/workflow-reviewed-final/run-1.txt`, `logs/workflow-browser-atomic/run-1.txt`다. 중간 HTTP 회귀1 NEW는 공개 Task read에 없는 내부 request_key를 읽은 fixture 오류로, 같은 DB의 실제 key를 조회하도록 고쳤다.

후속 독립 검토는 첫50개 폐기된 결과가 뒤의 유효한 결과를 막는 문제를 발견했다. RED4 후 폐기 결과 intent를 durable SUPERSEDED(빈 content, 발송 불가)로 기록해 다음 scan이 진행하도록 수정했다. invalid50+valid51번째 결과에서 worker2회로 유효한 회신1건과 invalid50의 SUPERSEDED를 확인했다. Task History INSERT trigger ABORT 시험은 Task INSERT, LINKED와 LINKED reply 예약을 모두 롤백하고 원래 READY/review reply만 유지함을 증명했다.

TaskStore hard-tier 초과는 기존 유한 JSON·64KiB·credential field 검증을 실제 payload 책임 `task_payloads.py`로 분리해 해결했다. 기존 `_safe_json` alias와 검증 동작을 유지하고 TaskStore는1035줄로 기존1060 상한 아래다. 후속 `a4a3ad4a0`은 호출자 공백 및 시험의 동일 count 조회를 별도 assertion으로 정리했다. 변경 파일 flake8 0 errors, harness lint 0 errors(기존 last_verified 경고28개). 전체 parent의 제한 크기 재판정과 source/Safety 최종 재검토는 아직 진행 중이다.
