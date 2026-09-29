## D-354 외부 장비는 mDNS로 서로를 찾는다 — IP 하드코딩·수동 설정 없이

**Status:** Accepted (2026-09-30, 구조 결정 + 펌웨어·발견 유틸리티 구현).

### Context

도크·신호등·향후 모든 외부 장비의 주소가 설정 파일에 IP로 박혀 있다. SD 카드를 갈아끼우면 IP가 바뀌고, DHCP 환경에서는 재부팅만으로도 바뀐다. 매번 `docks.json`·`signals.yaml`을 고치는 것은 프로토타이핑의 마찰이자 운영 사고의 씨앗이다.

ESP32는 mDNS(ESPmDNS)를 네이티브로 지원하고, Linux(avahi)와 Windows 10+도 mDNS를 해석한다. 장비가 스스로 `_rosy-dock._tcp.local`·`_rosy-signal._tcp.local` 서비스로 광고하면, 클라이언트는 주소를 몰라도 검색으로 찾는다.

### Decision

**1. 장비는 mDNS로 자신을 광고한다.**

| 장비 | 서비스명 | 인스턴스 | 포트 |
|---|---|---|---|
| 도크 | `_rosy-dock._tcp` | `dock_id` (NVS) | 80 |
| 신호등 | `_rosy-signal._tcp` | `signal_id` (NVS) | 80 |
| 관측 서비스 | `_rosy-observer._tcp` | hostname | 8095 |

펌웨어 `setup()`에서 `MDNS.begin(instance_name)` + `MDNS.addService(...)` — 3줄.

**2. 클라이언트는 `.local` 호스트명으로 접속한다.**

`docks.json`의 `host` 필드는 `rosy-dock-1.local` 형식. OS의 mDNS 해석기(avahi·Windows)가 IP를 찾아준다. IP가 바뀌어도 `.local` 이름은 바뀌지 않는다.

**3. 발견 유틸리티 (`core_common/discover.py`).**

`discover_devices(service_type)` → LAN의 해당 서비스 전체를 반환. `zeroconf` 패키지가 있으면 쓰고, 없으면 OS의 `avahi-browse`/`dns-sd`로 폴백. 어느 쪽도 없으면 `.local` 호스트명 직접 해석.

**4. 기존 IP 설정은 호환된다.**

`host`가 IP면 그대로 쓴다 (레거시 벤치). `.local`이면 mDNS. 발견된 장비가 DB에 없으면 대시보드에 "새 도크 발견"으로 표시하고 teach-by-docking으로 등록.

### Alternatives

- **UDP 브로드캐스트:** mDNS보다 단순하지만 표준이 아니고 Windows에서 안 된다. 기각.
- **중앙 등록 서버:** Fleet이 모든 장비를 등록하게 한다? Fleet이 죽으면 도크를 못 찾는다 — D-28의 "Fleet 없이도 충전" 원칙 위반. 기각.
- **DHCP 예약 (MAC→IP 고정):** 라우터 접근이 필요하고 로봇이 사이트를 옮기면 무효. 기각.

### Transition / validation

- 펌웨어: 도크·신호등 `setup()`에 mDNS 등록 3줄 추가
- `core_common/discover.py` 신설 (zeroconf 폴백)
- `docks.json` 예시를 `.local` 형식으로 갱신
- 계약 문서에 서비스명 표 추가
- 시험: discover 유틸리티 단위 시험 (zeroconf 부재 시 graceful fallback)

**Consequences:** 장비를 새로 사이트에 두면 전원만 연결하면 된다 — IP·설정·파일 수정이 필요 없다. 로봇이 새 사이트에 가도 발견이 자동으로 돈다.

**References:** [D-28 도크 계약](D-28-nav2.md), [D-352 공통 패턴](D-352-external-device-shared-pattern.md), ESPmDNS (ESP32 Arduino core), [RFC 6762 mDNS](https://www.rfc-editor.org/rfc/rfc6762), [RFC 6763 DNS-SD](https://www.rfc-editor.org/rfc/rfc6763).
