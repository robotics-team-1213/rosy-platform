## D-478 Pinky 검수 웹앱은 명시한 신뢰 망 주소에만 선택적으로 바인딩한다

**Status:** Accepted (2026-10-06, 사용자 결정 "검수자가 SSH 터널 없이 모델 PC 검수 앱을 Tailscale로 직접 연다"). 구현은 `--host` 옵션 하나다. 착지·push·배포·서비스화 승인이 아니다.

잇는 결정: [D-459](D-459-pinky-persistent-label-review-application.md) 8항을 확장한다(D-459 본문은 고치지 않는다) · [D-473](D-473-fleet-console-development-connection-mode.md)(Tailscale 100.64.0.0/10을 신뢰 개발 망으로 두고 명시 opt-in) · [D-471](D-471-same-network-auth-free-request-rejected.md)(같은 망 전면 무인증 기각).

### Context

D-459 8항은 검수 앱을 loopback 전용 HTTP로 정했다. 검수자는 모델 PC의 앱을 보려면 SSH 터널을 만들어야 한다. 검수자는 모델 PC와 같은 Tailscale tailnet에 있고 tailnet 구간은 이미 암호화된다.

### Decision

1. **`review_app.py --host <ip>`를 둔다.** 기본값은 `127.0.0.1`이고 동작은 바뀌지 않는다. 지정하면 그 주소에만 바인딩한다. 예: `--host 100.98.162.71`.
2. **받는 주소는 리터럴 IPv4 하나다.** loopback(127.0.0.0/8), RFC1918(10/8, 172.16/12, 192.168/16), link-local(169.254/16), Tailscale(100.64.0.0/10)만 허용한다. `0.0.0.0`, `::`, 공인 주소, 호스트 이름, IPv6는 시작 때 오류로 거부한다. 오류가 기본값으로 강등하지 않는다.
3. **Host/Origin은 주소를 더할 뿐이다.** 허용 Host에 `<host>:<port>`, 허용 Origin에 `http://<host>:<port>`를 loopback 형태와 함께 둔다. 다른 Host·Origin은 그대로 403이다. workspace별 쓰기 token(`X-Pinky-Token`), 본문 상한, 이미지 검증 등 다른 검사는 그대로다.
4. **HTTP만 쓴다.** TLS를 붙이지 않는다. tailnet 구간은 WireGuard로 이미 암호화되며, LAN에서는 평문이므로 신뢰한 LAN에서만 쓴다.
5. **사용자 인증은 없다.** 그 주소에 닿는 누구나 사진을 보고 수정하고 승인할 수 있다. token은 앱이 `/api/workspace`로 같은 주소의 누구에게나 내어주므로 외부 사이트의 교차 출처 쓰기만 막고 검수자를 증명하지 않는다. 검수자 신원은 D-459가 적은 대로 증명되지 않는다. 신뢰한 tailnet/LAN에서만, 필요한 동안만 켠다.

### Alternatives

- **`0.0.0.0` 바인딩.** 모든 인터페이스와 공인 망에 열려 D-471에 어긋나 기각.
- **호스트 이름 허용.** DNS 재바인딩 방어가 Host 검사에 의존하므로 리터럴 IP만 받는다.
- **SSH 터널 유지.** 사용자 요구를 못 채워 기각. 기본값은 여전히 loopback이라 터널은 계속 쓸 수 있다.
- **사용자 인증·TLS 추가.** 이 범위 밖이다. 필요하면 별도 ADR이다.

### Consequences

- 기본 실행은 이전과 같다. 명시 옵션을 준 실행만 tailnet 검수자에게 열린다.
- 검수 승인 기록의 신뢰 수준은 D-459와 같다(검수자 미증명).
- 수용: host pytest(기본은 100.98.162.71 Host 거부, `--host` 시 Host/Origin 허용·token 필수·외부 Origin 거부, `0.0.0.0`·공인 IP 시작 실패). 모델 PC에서 다른 tailnet 기기 브라우저로 접속하는 확인은 DEVICE 항목으로 남는다.

**References:** `learning/training/perception/dataset/review_app.py`, `learning/training/perception/test/test_review_app.py`, `learning/training/perception/docs/review-app.md`.
