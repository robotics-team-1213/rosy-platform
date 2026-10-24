# D-809: Legacy 937 검수 웹의 Account 경계와 사용자 감사 원장

**Status:** Accepted (2026-10-20)
**Related:** D-757, D-807
**Owner:** learning / perception curation

기존 937 검수 웹은 별도 HTML·JSON·CSV와 검수 결과를 유지하며 표준 Review 앱의
collaboration 설정을 받지 않는다. 자료와 사람 검수 기록의 의미를 바꾸지 않고 개인
Account 인증을 적용하기 위해, 기존 HTTP 서버 앞에 전용 loopback 프록시를 배치한다.
기존 foundation Account receiver의 PKCE·서명 검증·암호화 세션·회수 계약을 사용한다.

- 기존 backend와 인증 앞단은 서로 다른 loopback 포트에 둔다. HTTPS ingress는 인증
  앞단으로만 전달하며, 공개 Host와 unsafe Origin을 정확히 검사한다.
- 읽기는 해당 project의 learning.view를 요구한다. 검수 ok는 learning.approve,
  pending/fix/hold는 learning.edit를 각각 요구한다. 권한은 상속하지 않는다.
- 허용한 기존 조회 경로와 검수 경로만 전달한다. 사용자 cookie·bearer·신원 주장은
  backend로 전달하지 않는다. backend의 기존 Origin 검사를 위한 값은 인증 앞단이
  검증 후 고정 loopback 값으로 구성한다.
- 검수 변경 전에 신뢰한 account_id·resource·본문 hash·시간을 별도 보호 원장에
  남긴다. 성공·오류·결과 불명을 후속 기록한다. 전송 시간 초과나 중단된 intent는
  결과 불명이며 변경을 자동 재전송하지 않는다.
- 기존 검수 JSON에 새 actor 필드를 합성하거나 기존 label·원본·CSV를 변환하지 않는다.
  사용자별 감사의 정본은 앞단의 보호 원장이다.

표준 Review 앱으로의 즉시 자료 변환은 기존 검수 상태와 내보내기 의미를 다시 검증해야
하므로 선택하지 않았다. 이 경계는 기존 검수 앱을 보존하는 동안 유지한다. 장래 변환 시
자료·결정·사용자 감사의 대조와 명시적인 인수가 필요하다.

구현과 합성 시험은 배포·실사용 수용의 증거와 구분한다. [배포 안내](../deployment/legacy-937-account.md)는
기존 backend 차단, 보호 설정, 원본 hash, 실제 사용자 로그인과 회수 확인을 요구한다.
