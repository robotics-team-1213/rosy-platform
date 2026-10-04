## D-452 주소 대신 장비 신원과 역할로 네트워크 연결 대상을 찾는다

**Status:** Accepted (2026-10-04, 사용자 구현 요청; 구조 결정이며 구현·DEVICE/FIELD 수락은 별도)

### Context

사용자는 Pilot뿐 아니라 관제·로봇·카메라·모델 PC 등이 서로 주소를 입력하지 않고
네트워크에서 발견되기를 요청했다. D-354·D-432의 공통 발견 규약이 있으나 Fleet
컨테이너의 실제 service browser 의존성이 빠져 있고, 일부 소비자는 여전히 URL·SSH
host 설정만 사용한다. 호스트의 발견 목록 성공은 컨테이너 검색 성공을 뜻하지 않는다.
모델 PC는 현재 SSH 모델 배포 워처이며 새로운 LAN 추론 API가 존재하는 것은 아니다.

### Decision

1. 사용자가 선택하는 대상은 장비 이름·역할·승인된 신원이다. 주소는 연결 때마다
   resolver가 구하는 전달 정보로 다룬다. 일반 연결 화면에는 IP·URL 입력을 요구하지
   않는다. 기존 명시 주소는 이주·진단 호환 경로이며 신원 검증을 우회하지 않는다.
2. 같은 LAN에서는 DNS-SD/mDNS의 역할별 실제 서비스 광고와 공용 bounded cache를
   사용한다. 로봇·Fleet·Vision receiver·Dock·Signal의 기존 타입을 유지한다. 모델 PC의
   추가 발견은 실제 SSH 서비스와 모델 호스트 역할에 한정하며 존재하지 않는 추론
   API를 광고하지 않는다. 수신 listener가 없는 앱은 승인된 연결·source directory에서
   표현하며 가짜 TCP 서비스를 만들지 않는다. CORE의 여러 콘솔 화면도 한 runtime
   endpoint의 역할별 진입점이며 중복 서버가 아니다.
3. 연결은 승인된 expected hostname/identity와 CA·token·SSH HostKeyAlias를 유지한다.
   DHCP 주소 변경은 신원 변경이나 재등록 사유가 아니다. TLS SNI는 승인된 이름을
   사용하고 SSH는 기존 known_hosts와 StrictHostKeyChecking을 유지한다. 광고는 발견
   사실만 제공하며 인증·등록·제어 권한을 주지 않는다. 충돌·만료·신뢰 실패는 연결을
   차단한다. unsigned HTTP Dock·Signal 광고는 상태 관찰이며 제어 경로 승격 근거가 아니다.
4. CORE FleetAgent는 기존 지속 token·hostname·CA pin이 있으면 재연결 시 검색을
   우선한다. 모델 워처는 승인된 로봇의 논리 이름으로 현재 주소를 해석하되 기존
   shadow/intake·서명·SSH 소유권 검사를 유지한다. 기존 일회성 pairing credential을
   지속 Agent token으로 바꾸거나 장비를 자동 등록하지 않는다.
5. 웹은 UDP 검색을 직접 수행하지 않는다. backend의 인증된 장비 목록과 기존 승인된
   source/session 목록을 역할별 공용 선택 UI에 제공한다. 발견·승인·접속 준비·연결
   실패를 구분한다. 실제 listener나 확인된 연결 없이 사용 가능하다고 표시하지 않는다.
6. 사용자 범위는 같은 LAN과 다른 망의 승인된 장비 모두다(2026-10-04 추가 답변).
   mDNS는 local link 범위다. 다른 subnet/VPN/현장은 기존 승인된 관제 directory와
   정상 DNS/연결 profile을 사용한다. multicast를 인터넷으로 전파하거나 발견을 위해
   모든 주소·포트를 스캔하지 않는다. 서로 다른 망의 실제 연결 수락은 별도 검증한다.
7. Python cache의 단일 listener·최대 64 후보/대기·500ms resolve 상한과 Android의
   기존 TTL/복구 예산을 유지한다. 컨테이너에는 실제 동작하는 adapter 의존성을 넣고
   실제 UID/network namespace에서 확인한다. 광고 lifecycle은 서비스 시작·중지에
   묶고 반복 전체 검색 대신 변경/만료 이벤트를 처리한다.

### Validation and boundaries

주소 변경 후 같은 신원 재연결, 중복 신원/TTL 만료/종료, 잘못된 TLS·SSH 신원에서
credential 전송·배포·제어 없음, 공유 listener·후보 상한을 검증한다. Fleet container
UID의 실제 browser, 모델 호스트의 실제 SSH 광고, 인증된 웹 목록과 명시적 선택,
사이트/로봇 실행 SHA 및 LAN 트래픽은 각각 독립 증거로 기록한다.
모드 변경·정지 해제·구동이나 기존 가입 정보 초기화로 발견 검사를 통과시키지 않는다.
이 결정은 4자리 통합 코드 규격을 새로 구현했다는 주장이 아니다.

### Consequences

주소 필드 대신 승인된 대상 신원을 저장하고 서비스별 adapter를 공용 resolver에
연결해야 한다. 기존 HTTP 장비의 신뢰 전제가 부족하면 관찰 목록에만 나타나며,
물리 제어를 지원하려면 해당 장비의 승인된 인증 규약이 먼저 충족돼야 한다.

근거: [DNS-SD RFC 6763](https://www.rfc-editor.org/rfc/rfc6763.html),
[mDNS RFC 6762](https://www.rfc-editor.org/rfc/rfc6762.html), D-354, D-361, D-432.
