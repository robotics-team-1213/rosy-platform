# D-693 — Discord 요청과 현재 사건의 기명 인수 연결

**Status:** Accepted (source design only, 2026-10-12). 운영 배포·실제 인수·장치 수용은 별도다.

## Decision

Discord 요청을 현재 열린 line incident에 연결하는 것은 기존 Fleet 기명 인수다. Bot과 원문의 자연어는 사건·권한·판단 근거를 만들지 않는다. Console에서 현재 robot/stuck ID와 judgment revision을 확인하고 명시 확인 후 기존 line-stuck claim 소유자에 위임한다. revision 없는 resolver pause는 사건 인수 성공이 아니다.

서버는 현재 원문 owner/hash/review revision과 현재 operator mapping을 확인한다. 기존 gather/lock, open case, 판단 freshness/revision, 다른 담당자 claim 거절을 보존한다. 기존 IncidentHandoff의 동일 DB 트랜잭션 안에서 Discord 관계와 원래 메시지 회신 intent를 예약한다. 현재 사건·검토 변경 또는 원장/회신 실패는 claim·관계 전체를 rollback한다. 기존 안전상의 resolver pause는 실패 시에도 유지한다. 같은 원문과 사건의 재시도는 같은 인수를 읽으며 다른 사건으로 교체하지 않는다.

정지·취소·재개는 해당 기존 Console/CORE 소유자의 별도 확인과 admission을 사용한다. Discord 인수는 rearm, E-Stop 해제, motion, provider 호출 또는 추가 장치 writer를 만들지 않는다. 독립 모델 세션의 판단·자동 처리 정책은 변경하지 않는다.

사건 관계는 기존 tasks/incident DB에 저장한다. 요청 원문은 textContent로 표시하고 인증 lifetime/현재 선택을 확인한다. CLAIMED와 사건 CLOSED를 구분하며 CLOSED는 현재 사건 종료 기록이지 주행·목표 성공 보증이 아니다. Bot 회신은 고정 채널과 원래 메시지에만 생성하고 현재 mapping 재검사, UNKNOWN/기본 OFF 전송 규약을 그대로 사용한다.

## Verification and rollout

실제 기존 claim 소유자와 SQLite 원장을 사용해 current/stale/closed/changed judgment, 다른 담당자, hash/revision/권한 철회, 동일 재시도, 회신 실패 rollback과 resolver pause를 원격 검증한다. 실제 Chromium에서 원문 확인→현재 사건 선택→확인 취소/인수→원장 읽기와 기존 사건 화면 회귀를 확인한다. source 독립 검토와 parent 크기 재판정, 최신 main 통합/local FF, CI·서명 배포와 실제 Discord 왕복 증거가 남는다. 오프라인 로봇 FIELD는 별도 gate다.
