# D-944 팀 tailnet에서도 LCD 코드로 CORE에 페어링한다

**Status:** Accepted (2026-11-01, 사용자 결정 "Tailscale 대역 허용"). D-193 4의 출발지 조건만 넓힌다. 원격 시험·착지·장치 확인은 착지 기록이 증거를 가진다.

### Context

- 팀은 사이트 Wi-Fi와 Tailscale tailnet(D-477)으로만 접속한다. 외부 공개 경로는 없다.
- D-193 4는 `POST /api/v1/auth/pair` 출발지를 RFC 1918·AP·루프백으로 묶었다. Tailscale CGNAT `100.64.0.0/10`은 RFC 1918이 아니어서 tailnet으로 붙은 팀원은 LCD 코드를 보고도 로봇 대시보드에 페어링할 수 없었다(시험이 `100.64.0.1`을 403으로 고정).
- Fleet 개발 세션은 이미 tailnet을 받아 두 판정이 어긋났다(2026-11-01 네트워크 계층 조사).

### Decision

1. **코드가 필요한 길만 tailnet을 받는다.** `client_allowed(host, tailnet=True)`를 쓰는 곳은 LCD 일회용 코드 페어링(`POST /api/v1/auth/pair`)과 인증 없는 도달 확인 읽기(`GET /api/v1/auth/connection`)뿐이다. tailnet 대역은 `100.64.0.0/10`과 Tailscale IPv6 ULA `fd7a:115c:a1e0::/48`이다.
2. **코드 없는 길은 로봇 LAN 전용으로 남는다.** 개발 연결 세션(`/api/v1/auth/development-session`, D-471)과 최초 peer 승인 요청은 그대로 RFC 1918·루프백만 받는다. D-477 4(키 없는 접속 표면을 tailnet으로 넓히지 않는다)와 같은 이유다.
3. 속도 제한·코드 폐기·토큰 수명(D-193 4·5)은 바뀌지 않는다.

### Consequences

- tailnet 팀원은 LCD 코드를 받아 원격에서 페어링할 수 있다. 코드는 기기 화면에만 보이므로 코드를 볼 수 있는 사람만 페어링한다.
- tailnet 계정이 탈취되면 페어링 시도 표면이 늘지만, 코드·속도 제한·5회 폐기가 그대로 막는다.
- 다른 "LAN" 대역 정의(Fleet 개발 세션, mDNS, SSH 도우미 등)의 통일은 이 결정의 범위가 아니다.

### Alternatives

- **`ALLOWED_NETWORKS`에 tailnet을 통째로 추가:** 개발 무코드 세션과 peer 승인까지 tailnet으로 열려 D-477 4와 어긋난다. 기각.
- **그대로 둠:** 팀의 실제 접속 방식(사이트 Wi-Fi + Tailscale)과 맞지 않는다. 기각.
