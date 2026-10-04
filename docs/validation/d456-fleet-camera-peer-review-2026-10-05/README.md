# D-456 Fleet/Cam LAN 승인 소스 검토

독립 검토자 `/root/ship_fleet_cam_merge`: 최종 35 경로 SPEC·Quality·Safety SOURCE PASS.
원본 31 경로와 namespace·공용 필드·인증 epoch·비밀키 배치 delta의 정규화 해시가
실제 부모 적용 소스와 일치한다. 검토 영수증 SHA256: `41063176de55493ec81e0f2350bdad97f056d1931071695a4d9b1d194833d3ec`.

기존 named site operator가 영상 source 승인·SQLite nonce·credential·감사를 소유한다.
관계 키·source·generation·현재 issuer가 일치해야 재발급하며 누락 marker를 legacy로
낮추지 않는다. 영상 승인·재연결은 CORE 제어·lease·촬영 시작 권한을 발급하지 않는다.
CA와 hostname은 실제 configured TLS를 검증한다. 광고는 capability hint이며 신원이 아니다.

독립 실제 Chromium probe에서 401/403/404 후 보호 목록과 버튼을 지우고 같은 인증 epoch의
반복 조회·POST가 0임을 확인했다. 명시적 새 epoch에서는 같은 자격도 다시 확인한다.
물리 사용자 승인이나 실제 네트워크 자격 철회 수용은 아니다.

D-362 크기 재판단: Fleet 34,792줄, 증가 926줄 = backend 756 + web 135 + 기존 연결 35.
각 신규 owner 모듈은 최대 232줄이며 app 589줄, console 1,159줄 불변이다.
기존 Fleet server/UI 분할 대기열과 package +150·production 600·web 800·1000 초과
파일 성장 0 규칙을 유지한다. 새 모듈은 기존 영상 승인 소유자의 SQLite·TLS·API·UI로
나뉘고 CORE 인증 서버나 actuator writer를 복제하지 않는다. 이번 측정 재판단은 이후
임의 성장이나 기존 분할 의무의 면제가 아니다.

실제 부모 통합: peer/deploy/shared-controls 검사 133 PASS와 기존 CORE kind 선언 1 FAIL.
기존 승인/거절 kind를 명시적 리터럴로 유지한 뒤 공용 UI·실제 Chromium CORE 승인
시험 29 PASS. 기존 camera v1·새 session namespace·API reference 82 PASS.
원본 실패 로그를 보존한다. POSIX 키 권한·서명 site/Android 배포·실제 LAN 최초 승인·
DHCP/오프라인 재연결·발열 대응은 별도 수용이며 완료로 표시하지 않는다.
