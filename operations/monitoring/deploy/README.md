# Independent Monitoring deployment

이 디렉터리는 검토·시험할 배포 입력이다. 설치·서비스 활성화·실제 LAN/TLS 수용을 수행한 기록은 아니다.
Linux/POSIX, Python 3.12 이상을 대상으로 한다. Windows PC는 TLS 브라우저로 조회한다.

## Build and prepare

저장소의 검증된 커밋에서 전용 가상 환경을 만들고 설치한다.

```sh
python3 -m venv /opt/rosy-monitoring/venv
/opt/rosy-monitoring/venv/bin/pip install ./contracts/foundation ./operations/monitoring
/opt/rosy-monitoring/venv/bin/python -m rosy.monitoring.web_assets --repo "$PWD" --output /opt/rosy-monitoring/web
```

출력 경로는 없어야 한다. builder는 고정된 UI·공용 파일만 새 묶음에 복사하며 소스 사본을 저장하지 않는다.
배포 교체 시 새 릴리스 경로에서 만들고 기존 묶음을 덮어쓰지 않는다. `/opt`의 코드·묶음은 root 소유로 유지한다.
`rosy-monitoring` 시스템 사용자·그룹을 만들고 로그인·sudo 권한을 주지 않는다.

`site.yaml`, `aggregate.yaml`, `direct-central.yaml` 중 하나를 실제 등록 대상으로 수정해
`/etc/rosy-monitoring/monitoring.yaml`에 설치한다. `.example.invalid`는 접속 불가능한 예시 주소다.
CORE의 `id`는 실제 `robot_id`, peer의 `id`는 실제 원격 `collector_id`여야 한다.
peer가 전달할 사이트는 서로 겹치지 않아야 한다. 직접 수집과 peer 수집으로 같은 사이트를 중복 소유하지 않는다.
host_state 경로는 기존 owner가 만드는 보고 파일로 바꾸고 전용 사용자에게 읽기 권한만 제공한다.
파일·상위 디렉터리가 읽히는지 확인하며 owner의 private 데이터를 world-readable로 바꾸지 않는다.

환경 변수 참조마다 독립적인 32자 이상 ASCII 비밀값을 발급한다. 운영 키를 예시·명령행·Git에 넣지 않는다.
`credentials.env`는 systemd EnvironmentFile 형식이며 root 소유 0600으로 설치한다.
사이트 `central-reader`의 키는 중앙 `MONITORING_SITE_UPSTREAM`에 같은 값으로 전달하고,
중앙 operator 키와는 구별한다. reader별 사이트 허용 범위를 최소로 제한한다.
설정은 root 소유 0640, 그룹 rosy-monitoring으로 둔다. 사설 CA는 `ca_bundle`의 절대 경로로 등록한다.

`rosy-monitoring.service`를 `/etc/systemd/system/`에 설치하기 전에
`systemd-analyze verify`로 대상 OS에서 검사한다. `StateDirectory`가 0700으로 생성되는지 확인한다.
시험 PC에서는 설치된 wheel의 실행 파일 위치만 치환한 unit을 실제 systemd 파서로 검사한다
(`test/test_native_artifact.py`). 이는 대상 PC의 고정 경로·사용자·권한이나 서비스 기동 수용을 대신하지 않는다.
상태 DB와 lock은 이 서비스만 쓴다. Fleet를 unit 의존성에 추가하지 않는다.
서비스 시작은 해당 호스트 운영 절차에서 별도로 수행한다.

## Network

8786은 loopback 전용이다. 방화벽에서 이 포트를 외부에 열지 않는다.
`Caddyfile.example`의 TLS site를 기존 프록시에 통합하고 실제 인증서·DNS를 검증한다.
`/monitoring/` UI 경로는 prefix를 제거하고, `/api/monitoring/`은 그대로 전달한다.
공용 UI 자산도 `/monitoring/common/`으로 전달하므로 Fleet 정적 서버가 없어도 열린다.
Fleet의 같은 origin utility 링크를 쓰려면 그 TLS site에도 위 두 경로를 등록한다.
다른 origin을 쓸 경우 고정된 운영 링크를 사용하며 URL에 키를 넣지 않는다.

사이트 → CORE/Fleet는 등록된 HTTPS 읽기만, 중앙 → 사이트는 scoped Monitoring API 읽기만 허용한다.
이 경로로 명령·자동 복구를 보내지 않는다. 중앙이 없어도 사이트 관측은 계속된다.
Grafana는 향후 후보이며 이 배포에 설치하지 않는다.

## Acceptance and recovery

외부 supervisor에서 PID와 `/monitoring-health`를 확인한다. 자신의 200 응답만으로 전체 정상 판정을 내리지 않는다.
실제 사이트에서 인증 거부·scope 거부·중앙 단절·사이트 단절·TLS 실패를 확인하고
화면의 원천 판정과 신선도가 서로 구별되는지 기록한다. host pytest·합성 브라우저는 이 수용을 대신하지 않는다.
256 MiB 상한은 시작값이며 최대 등록 규모의 실제 메모리 관측 후 조정한다.

복구는 기존 운영자가 수행한다. 손상·다른 소유자 DB로 시작이 거부되면 서비스를 멈추고
DB·lock·로그를 보존해 원인을 확인한다. DB 삭제·새 이름으로 재시작해 오래된 관측을 최신으로 만들지 않는다.
코드 롤백은 이전 검증 릴리스로 하고, 상태 schema 호환성을 확인한다. 재시작 후 보고는 다시 관측할 때까지 지연으로 표시된다.
