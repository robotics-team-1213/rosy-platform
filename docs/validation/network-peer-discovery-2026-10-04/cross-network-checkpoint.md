# D-452 승인된 다른 망 연결과 선택 로봇 CLI — 소스 검증

2026-10-04, 최신 main과 통합된 `integrate/ui-ship` source.

CORE fallback은 `allow_dns_fallback: true`와 canonical `approved_directory_url`을
명시한 승인 profile에서만 가능하다. 일치 광고 부재만 허용하고 광고 충돌·오류,
TLS·health role·401/403 실패에 우회하지 않는다. 기존 expected_hostname SNI·CA로
health를 먼저 검사하며 인증 전 Agent token을 보내지 않는다. legacy hub_url은
fallback 대상이 아니다. 새 등록·키·권한을 만들지 않는다.

모델 CLI는 전체 roster 문법을 검증한 뒤 선택한 논리 로봇만 주소 해석한다. 다른
offline 로봇 때문에 선택한 대상의 doctor가 실패하지 않으며 SSH key alias는 유지한다.

- CORE: 병합 후 85 PASS, SKIP 0, NEW 0.
- 모델 CLI: 63 PASS, 기존 SKIP 1, NEW 0.
- 실제 로컬 TLS fixture: health 200·401·403·wrong role·wrong SNI 검증,
  credential header 없음, 인증서 거부 시 HTTP 요청 없음.
- 실제 doctor orchestration의 two-peer 회귀: 선택한 pinned alias만 접촉.
- 독립 SPEC·Quality·Safety source review PASS.

이는 실제 서로 다른 네트워크의 장비 연결·모델 PC 설치·signed candidate·사이트/로봇
실행 SHA 수락이 아니다. 테스트 PKI와 로그/hash receipt는 X 드라이브에 있다.
