# Account 활성화 선행 조건 재확인

2026-10-19 후속 읽기 전용 확인. [이전 운영 readback](governance-and-site-readback.md) 이후 운영 전환 가능 여부를 확인했다. 작업 소스 HEAD는 `8d05ced7b`였으며 작업 트리는 깨끗했다.

- 실행 Fleet와 proxy의 health는 모두 `healthy`다. 두 컨테이너의 이미지 tag는 `d6f434cd06ac87a7882218ff17931894babc1f9b`다. OCI revision label은 없으므로 tag만으로 실제 이미지 내용과 소스 SHA의 일치를 입증하지 않는다. 이번 Account 소스 변경의 설치 증거가 아니다.
- 기존 사이트 MagicDNS 이름의 443에 현장 호스트에서 TCP 연결을 시도했으나 `ConnectionRefusedError`였다. 인증서 검증을 끄지 않았다. 연결 단계에서 실패했으므로 TLS 신뢰·Account callback 검증은 미실행이다.
- Tailscale status의 HTTPS 관련 capability는 존재하지만 `CertDomains` 목록은 비어 있다. 이것만으로 tailnet 관리 콘솔의 HTTPS 정책을 확정하지 않는다. 앞서 확인한 빈 serve 설정·443 바인딩 부재와 함께 현재 후보 issuer가 사용 가능하다는 증거는 없다.

실제 전환을 막는 조건은 보호 설정/관리 권한, 신뢰된 issuer HTTPS 443, 정확한 receiver callback/resource 및 native 설치 signer다. 기존 관리자 후보의 존재만으로 이 조건이 충족되지 않는다. 사용자 비밀번호·sudo 인증을 채팅으로 요청하거나 Docker root 권한으로 보호 파일을 우회하지 않았다. 운영 변경·새 키 생성·도메인 활성화·서비스 재시작은 수행하지 않았다.

운영 관리자가 기존 접근 정책 안에서 issuer TLS/443 및 보호 설정 접근을 준비한 뒤 기존 서명 candidate 절차로 전환하고 앱별 실사용·회수·격리 복구를 확인해야 한다. 설치·실사용이 미완료이므로 지속 목표는 active다. 이번 기록은 새 제품 변경이나 시험 통과 기록이 아니다.
