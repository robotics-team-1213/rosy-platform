# D-452 발견과 승인 신원 연결 — 첫 소스 검증

날짜: 2026-10-04. 통합 branch: `integrate/ui-ship`. 구현과 실기 수락은 구분한다.

- 공통 metadata·TXT vector·human profile 검사: 최종 72 PASS. 승인 DNS·미해결 주소·VPN,
  기존 literal-IP profile과 mDNS 거부 경계를 포함한다. metadata 자체는 13 PASS다.
- CORE FleetAgent: 60 PASS, 독립 SPEC·Quality·Safety source review PASS. 지속 token과
  hostname/CA pin이 있는 경우 새 주소를 발견하며, 충돌·신뢰 실패에 legacy URL로 우회하지 않는다.
- 모델 워처·CLI·SSH 광고: 199 PASS / 기존 platform SKIP 22, NEW 0. 새 resolver/provider
  검사는 skip 없이 실행됐다. WSL `bash -n`, diff 검사 및 독립 source review PASS다.
- 모델 resolver는 논리 HostKeyAlias·known_hosts를 유지하고 관찰과 배포 직전에 재해석한다.
  만료·충돌·SSH 신원 실패에는 push와 배포 attempt 증가가 없다. DNS fallback은 승인된
  로컬 policy의 absence-only 선택이다. 실제 SSH listener와 SSH-2.0 banner 확인 후만 광고한다.
- 모델 광고 검사의 실제 socket banner와 소유 child 회수는 host LOCAL 증거이며,
  모델 PC 설치·systemd 활성화·다른 망의 실제 연결·로봇 배포 성공을 뜻하지 않는다.
- 기존 CLI 파일 크기 verdict 615 + 허용 regrowth 150 내의 640줄이다. 예외 상한을
  늘리지 않았고 recorded-verdict 검사는 PASS다.

Dock·Signal consumer는 재지정하지 않았다. Dock 상태는 착좌·충전·배터리 판단에,
Signal 인증 상태 조회는 token 전송·watchdog 감독에 사용된다. unsigned 광고만으로
이 권한을 바꾸지 않으며 발견 목록의 readiness는 unknown이다(D-452).

모델 PC 설치·Fleet container 실제 UID/network namespace의 LAN 검색·인증된 operator
전체 웹 화면·최종 CI·서명 후보·사이트/로봇 실행 SHA 및 실제 LAN 트래픽은 아직 별도 검증이다.
로봇 SSH는 마지막 재조회에서도 timeout이었다. 가입 정보·키·정지·구동 상태를 바꾸지 않았다.
개인 원본 로그와 hash receipt는 X 드라이브 세션 폴더에 보존했다.
