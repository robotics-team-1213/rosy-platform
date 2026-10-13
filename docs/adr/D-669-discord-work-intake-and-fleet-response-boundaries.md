## D-669 Discord 대화 작업 요청과 Fleet 대응 경계

**Status:** Proposed (2026-10-12). 사용자 방향은 대화 작업 요청, 기본 관리는 Fleet Console, 위험 상황은 Discord 대응이다. 이 문서는 새로운 Discord 실행 권한이나 실제 장치 활성화를 수용하지 않는다.

### Context

D-661의 incoming webhook은 Fleet에서 Discord로 알림을 내보내는 경로다. 대화 수신·사용자 연결·작업 후보 생성은 없다. 지정 채널의 연결 확인 메시지 1건은 HTTP 200과 UI 수신까지 확인했지만, Fleet outbox·기명 인수·실제 조치·목표 검증을 통과한 사건은 아니다.

`core_common.intent`와 `/api/fleet/do`는 구조화된 JSON 문법과 실행 경로다. 자연어를 그대로 전달할 수 없다. 일반 Mission은 기존 제안 소유자의 admission을, Cell Job은 service 제안과 다른 기명 운영자의 admission을 요구한다. Discord Bot을 공용 operator로 등록하여 이 구분을 우회하면 안 된다. D-655/D-664 작업·survey/read-only 경계를 유지한다.

### Decision proposed

1. 일반 작업은 `대화 수신 → 요청 원장 → 후보 작성 → Fleet Console 확인 → 기존 proposal/resolve/admit 또는 Task 제출 → CORE/OMX → 결과 근거 → 원래 대화`로 연결한다. 위험 사건은 `현재 사건·근거 → Discord 통지 → 기명 담당 인수·대응 요청 → Fleet 권한·사건 재검사 → 기존 대응 경로 → 재관측·종료 근거`다. 통지·인수·제출·수락·실행·목표 달성·사건 종료를 구분한다.
2. 검증된 Discord transport envelope의 snowflake 사용자 ID를 Fleet의 기명 principal과 비공개 설정에서 연결하고 Fleet이 principal을 결정한다. 표시 이름, Discord 역할 이름, 본문이나 Bot 호출자가 넘긴 principal은 인증이 아니다. 기본 미연결 사용자는 요청/실행·인수를 만들지 않는다. Bot은 intake 전용 transport 자격만 가지며 공용 operator bearer·`site-console`·development fallback이나 장치 credential을 사용하지 않는다. 승인 시 Fleet의 현재 계정·권한을 재확인한다.
3. 허용 guild/channel에서 Bot을 명시적으로 대상으로 한 요청만 받는다. Bot·webhook 메시지와 DM은 제외한다. `(guild_id, channel_id, message_id)`와 고정 내용 hash로 중복을 막고, 같은 ID의 수정은 기존 후보를 몰래 변경하지 않는다. 요청자·원문 revision·후보·승인자·Fleet ID·결과 revision을 연결한다. 재연결·재시작·불명 제출을 자동 재실행하지 않는다.
4. 일반 작업의 기본 확인·승인은 Console이다. 위험 상황의 Discord 대응은 사건 조회·기명 인수 요청·기존 정지/취소 요청의 검토부터 시작한다. Discord에 쓰인 ‘위험’이라는 문장이나 모델 판단이 움직임, E-stop 해제, rearm, 복구 이동의 허가가 되지 않는다. CORE의 즉시 보호는 사람 답변을 기다리지 않는다. Bot의 기명 인수/정지 권한 확장은 별도 API·인증 계약과 시험 후 수용한다.
5. 자연어 해석은 Decision의 후보 전용 책임이다. 기존 World/roster/capability/map evidence로 대상·위치·의미를 확인하며 불명 대상이나 모호한 작업은 질문/보류로 남긴다. 모델이 URL·principal·예산·명령 경로를 고르지 않는다. D-640 provider/FIELD HOLD를 유지하고 검증된 launcher 없이 실제 모델을 호출하지 않는다.
6. 소스 수신·외부 transport는 `integrations/messaging/discord`, 요청 연결·원장·권한·기존 서비스 호출은 Fleet, 의미 후보는 Decision, 순수 workflow/goal evidence는 execution이 소유한다. `fleet/incidents`는 사건 인수·통지 책임을 유지한다. 새 범용 orchestration 서비스나 두 번째 Mission/Job DB를 만들지 않는다. 새 holder는 D-427/D-429/D-430 관계·manifest·설치 closure를 함께 수용한 뒤 만든다.
7. 응답은 원래 채널/요청에 묶이며 새 목적지를 메시지 내용에서 받지 않는다. provider 수락·실제 수신과 장치 결과를 별도로 기록한다. Discord 장애가 CORE 안전이나 Fleet 작업 원장을 중단시키지 않는다. 사람 검수·실제 목표 증거 없는 성공 표현은 금지한다.

### Alternatives

Console 링크만 제공하는 방식은 기존 계약으로 가장 빨리 동작하지만 대화 수신이 없다. 대화 후보와 Console 승인을 연결하는 방식을 먼저 권고한다. Discord에서 일반 작업을 직접 승인·실행하는 방식은 운영자 연결·승인 화면·신선도·중복 방지 계약이 추가로 필요하므로 후속이다.

### Validation

다른 서버/채널/사용자·Bot 자기 응답·수정/재전송·권한 철회·잘못된 대상·모호한 작업·오래된 사건·중복 승인·UNKNOWN 재시작·로그 비밀 비노출을 거절한다. 일반 Mission과 Cell Job의 서로 다른 승인 규칙, Task/Mission/장치 결과의 의미를 기존 시험으로 보존한다. 실제 수용은 한 요청의 수신→후보→기명 확인→Fleet readback→장치 결과→목표 근거→대화 결과까지 별도 기록한다.

**References:** D-661, D-640, D-655, D-664, D-298, D-369, D-427, D-429, D-430. [설계·점검](../plans/2026-10-12-discord-fleet-pipeline-design.md), [실행 계획](../plans/2026-10-12-discord-fleet-pipeline.md).
