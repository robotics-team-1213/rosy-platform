## D-936 ROSY Monitoring은 관제 PC에서 서명 사이트 스택의 선택 서비스로 실행한다 (D-876 배치 보충)

**Status:** Accepted (2026-10-30, 사용자 결정). 소스·시험은 이 변경으로 구현한다. 관제 PC의 설정·키 준비, 서명 후보 반영, 실제 화면 수용은 별도다.

### Context

- D-876은 Monitoring을 Fleet과 따로 도는 프로세스로 정했지만 실행 위치는 정하지 않았다. 배포 안내는 호스트 systemd와 별도 TLS 프록시를 예시로 들었다.
- 관제 PC의 HTTPS 프록시는 서명 이미지로 배포되는 Caddy 컨테이너다(D-301, D-441). 이 컨테이너는 호스트 loopback에서 도는 서비스에 닿지 못한다.
- Fleet 화면에는 이미 `/monitoring/`으로 가는 "시스템 상태" 링크가 있다. 프록시에 이 경로가 없어서 지금은 열리지 않는다.
- 사용자 결정(2026-10-30): 상태 보기는 Monitoring 하나로 모은다. 제어는 Fleet의 운영자 권한에 두고, 자동 복구는 host-guard에 둔다. 설치는 사이트 스택 컨테이너로 한다.

### Decision

1. **선택 overlay로 켠다.** `compose.monitoring.yaml`을 `ROSY_SITE_PAIRING_COMPOSE`에 더한 관제 PC에서만 `monitoring` 서비스가 뜬다. overlay 순서는 pairing·omx·workcell 뒤, Account 앞이다. 설정·키가 없는 PC의 기본 스택은 그대로다.
2. **새 이미지를 만들지 않는다.** 서명된 Fleet 이미지에 Monitoring 소스와 화면 묶음을 함께 싣고, 별도 서비스·프로세스·상태 볼륨·키로 실행한다.
   - Fleet의 PYTHONPATH에는 Monitoring을 넣지 않는다.
   - 의존성은 Fleet 이미지에 이미 고정된 버전을 쓴다.
   - 서명 이미지 목록(D-887)은 바뀌지 않는다.
3. **업데이트기는 monitoring을 Fleet 이미지 동반 서비스로만 허용한다.**
   - 서명 후보에 overlay 파일 한 쌍(`compose.monitoring.yaml`, `Caddyfile.monitoring`)이 있어야 하고, manifest의 `monitoring`이 참이어야 한다.
   - overlay가 켜졌을 때만 서비스 집합에 `monitoring`을 더한다. 그 이미지는 후보의 Fleet 이미지여야 한다.
   - drift 검사(읽기 전용 root, 비특권)는 다른 서비스와 같다.
   - 건강 판정과 롤백 관문에는 넣지 않는다. Monitoring이 고장 나도 현장 업데이트를 되돌리지 않는다.
4. **외부로 포트를 열지 않는다.**
   - 실행기는 `--host`(IP 리터럴, 기본 `127.0.0.1`)를 받는다. 컨테이너에서는 내부 망 `site_backend`에서만 받는다.
   - 열람자는 기존 TLS 프록시의 `/monitoring/`, `/api/monitoring/`, `/monitoring-health`로 들어온다. 프록시는 키를 더하지 않는다.
   - 프록시는 monitoring을 기다리지 않는다. monitoring이 없으면 그 경로만 502다.
5. **원천은 Fleet이 이미 읽는 것만 읽는다.**
   - host-guard·host-state 보고 디렉터리를 읽기 전용으로 마운트한다.
   - Fleet은 `https://fleet`을 `site_ca`로 검증해 viewer 키로 읽는다.
   - 키 두 개(`MONITORING_SITE_READ`, `MONITORING_FLEET_UPSTREAM`)는 Git 밖의 별도 비밀 디렉터리에 둔다. `secret_exec`가 root로 읽은 뒤 uid 10001로 내려간다.

| 관계 | 내용 |
|---|---|
| D-876 | 독립 프로세스·읽기 전용·제어 없음은 그대로다. 실행 위치만 정한다 |
| D-427·D-429·D-430 | 소스 위치는 바뀌지 않는다(`operations/monitoring`, `applications/monitoring`). safety 태그 경로는 건드리지 않는다 |
| D-301·D-441·D-887 | 서명 후보·자동 업데이트를 그대로 쓴다. 이미지 목록은 같고 overlay 파일 한 쌍만 더한다 |

### Alternatives

- **호스트 systemd + 별도 Caddy:** docker가 멈춰도 볼 수 있다. 대신 자동 업데이트 경로를 새로 만들어야 하고, Fleet 링크도 다른 주소로 바꿔야 한다. 관리할 부품이 늘어서 택하지 않았다.
- **새 서명 이미지:** 가장 분리되지만, 서명·검증·업데이트기의 이미지 목록을 모두 바꿔야 한다. 이번 범위에 비해 크다.

### Consequences

- docker 전체가 멈추면 Monitoring도 멈춘다. docker는 host-guard가 살린다.
- Fleet 이미지가 바뀔 때 Monitoring도 같이 바뀐다.
- 남은 일: 관제 PC의 설정·키·Fleet viewer 계정 준비, 서명 후보 반영, 실제 열람 수용(인증 401, 범위 403, Fleet 정지 중 조회).
