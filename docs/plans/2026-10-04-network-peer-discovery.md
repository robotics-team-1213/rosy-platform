# 네트워크 장비 자동 발견과 논리 대상 연결 실행 계획

근거: D-452. 사용자 추가 요청이며 기존 UI 커밋·merge·배포 목표를 유지한다.

확정 범위(2026-10-04 답변): 같은 망 직접 검색 + 다른 망의 기존 승인 장비 directory.
현재 미해결 주소는 null/unknown으로 표시하고 연결 시 승인 DNS profile을 해석한다.
새 credential·등록·인터넷 multicast relay를 자동 생성하지 않는다.

1. 기존 UI 실패 수정과 실기 기록을 독립 검토 후 커밋하고 최신 main/origin과 통합한다.
2. Fleet 이미지의 실제 browser 의존성을 넣고 동일 cache/정본 TXT 분류를 사용한다.
   역할별 장비 목록을 backend와 공용 선택 UI에 연결한다. 기존 승인·등록 정보를 보존한다.
3. 모델 호스트는 실제 SSH 서비스의 발견 profile과 광고 lifecycle을 추가한다.
   모델 워처의 논리 이름 resolver는 매 연결마다 주소를 갱신하고 기존 HostKeyAlias·
   known_hosts·서명/intake/shadow 검사를 유지한다. 가짜 모델 추론 listener는 만들지 않는다.
4. CORE FleetAgent의 승인된 hostname/CA profile은 explicit URL보다 발견을 우선한다.
   Dock·Signal은 unsigned 광고를 역할 목록에만 관찰한다. 현재 active consumer의 URL은
   충전 판단·token 전송·watchdog 감독을 바꾸므로 광고로 재지정하지 않는다(D-452 경계).
5. protocol/TXT fixture·API ref·ADR를 실제 변경과 함께 갱신한다. 각 소유 범위의
   의미 있는 주소 변경·만료·중복·잘못된 신원·종료 검사를 실행하고 독립 검토한다.
6. 최종 SHA를 push하고 정확한 원격 CI·서명 후보·사이트/앱/로봇 실행 SHA를 확인한다.
   실제 container UID discovery와 정상 인증 장비 목록을 확인한다. 재부팅 반복·접속
   불안정·운영자 로그인·다른 subnet 전제는 미확인 상태를 명시한다.

개인 주소·raw token·원시 로그·스크린샷은 X 드라이브에 보관한다. 실제 장비 검색과
UI fixture, SSH 접속과 안정된 CORE 연결, 코드 반영과 FIELD 수락을 구분한다.
