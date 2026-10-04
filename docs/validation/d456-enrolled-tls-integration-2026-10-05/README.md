# D-456 기존 관제 등록의 TLS 전송 통합

기존 encrypted enrollment의 자격·ID·발급자·만료를 유지하고 공개 설정으로 승인된
호스트 이름과 CA를 결속한다. REST와 WSS는 같은 발견·신뢰 소유자를 사용한다.
신원 검증을 기다리는 동안 권한이 중단되면 이후 자격 전송을 거절한다. 같은 등록부의
공개 transport marker는 설정 누락·재시작·오프라인 때 HTTP 복귀를 차단한다.
정상 등록 해제 이외의 marker 초기화나 CA 교체 절차를 이 변경에서 제공하지 않는다.

독립 검토자 `/root/ship_core_merge`: SPEC·Quality·Safety SOURCE PASS.
전송 검토 영수증 SHA256:
`9a6d4e5aa77594060adf2d3f52a5b917d91f3cf3c32497507efdec8e4c86167b`.
초기 구조 검토는 CLI의 명시된 다음 옵션 전 builder 분리 조건 때문에 HOLD였다.
기능별 조립을 분리한 후 구조·SPEC·Quality·Safety SOURCE PASS로 재판정했다.
최종 builder 검토 영수증 SHA256:
`0c2a2bc9c602224016592db471b3c2c659c3432f5b8b68650c0069585ed90df0`.

D-362 재판정의 동일 production 필터·physical line 측정은 Fleet 35,606줄이다.
기존 판정 35,137줄 대비 469줄이며 이전 동시 작업 80줄, TLS 전송 변경 364줄,
이번 조립 분리의 순증 25줄로 구성된다. TLS 추가 364줄은 새 trust owner 228,
enrollment 91, store 25, transport 12, CLI 8줄이다. 조립 분리는 CLI 652→586,
새 console builder 91줄이다. mission·pairing 조립 본문 AST는 동일하며 enrollment의
설정 인자만 명시적으로 전달한다. 선택 기능 import와 기존 pairing alias를 보존한다.
localization은 기존 별도 builder를 유지한다.

CLI가 600줄 미만이 되어 기존 예외 항목을 제거한다. 새 91줄 builder와 228줄 TLS
owner는 파일 기준 안에 있다. enrollment 784줄은 기존 664+150 판정 범위 안이다.
Fleet 판정 종류는 split으로 유지하며 기존 B2/server·UI 분리 대기열을 없애지 않는다.
production 600, web 800, package 10,000, 재성장 +150, 1,000 초과 성장 0과 검사
범위·종류·허용량을 변경하지 않는다. 숫자 변경만으로 초기 HOLD를 통과시키지 않았다.

전송 변경 통합 시 원본 관련 회귀 207 PASS/2 Windows SKIP(57.04초)를 확인했다.
최종 builder의 원본 CLI·TLS 회귀는 55 PASS/1 Windows SKIP(34.83초)이며, 서로
겹치는 검사를 합산하지 않는다. TLS 안전장치 6개를 실제 변이해 각각 RED를 확인하고
변경하지 않은 원본을 복원한 검사에서 23 PASS/1 SKIP를 확인했다. Windows symlink
권한 및 POSIX mode 제한은 Linux CI·실제 배포 검증을 대신하지 않는다.

부모 통합 트리의 원본 CLI·TLS·module structure 검사는 88 PASS/1 Windows SKIP
(49.35초)다. 초기 P6의 package 성장 RED 뒤, 검토된 조립 분리와 기록 반영으로
전체 33개 module structure 검사를 통과했다. 검사 임계값이나 스캔 범위는 유지했다.

두 실제 로봇의 공개 HTTPS identity와 TLS calibration 읽기 검사는 통과했다.
이것은 관제 설정 적용·실제 HTTPS/WSS 자격 전달·Pilot 승인/재연결·새 Camera Peer
승인·발열 대응·주행 수용을 뜻하지 않는다. 공개 TLS 설정 파일은 준비했지만 현재 관제
SSH 계정은 root 설정 쓰기 권한이 없고, 새 camera receiver 설정과 유효한 named
operator 로그인도 확인되지 않았다. 실제 연동이 확인되지 않은 범위는 FIELD 미완료다.
원본 로그·변이·리뷰 영수증은 `X:/DevTemp/rosy-ui-ship/enroll-tls/`에 보관한다.
