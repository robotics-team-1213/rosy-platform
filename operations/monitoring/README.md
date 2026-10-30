# ROSY Monitoring

ROSY 시스템 모니터링의 독립 Python wheel은 `rosy-monitoring`, import는 `rosy.monitoring`이다.
소유권과 배치 결정은 [D-876](../../docs/adr/D-876-rosy-monitoring-independent-site-and-aggregate.md)을 따른다.

관측 모델·설정·자격·사이트별 캐시, 원천 수집과 읽기 API를 제공한다.
독립 실행 CLI와 별도 [상태 화면](../../applications/monitoring/README.md)을 제공한다.
native 서비스·설정·TLS 프록시 입력은 [배포 안내](deploy/README.md)를 따른다.
실행 중인 Fleet 프로세스나 ROS를 import하지 않는다.
HTTP 경로·인증·시간 전달·보존 한도는 [Monitoring API](../../docs/reference/rosy-monitoring-api.md)가 정본이다.

저장소 루트에서 wheel을 설치한다.

```sh
python -m pip install ./contracts/foundation ./operations/monitoring
```

## 독립 실행

Linux 네이티브 배포를 대상으로 한다. 실행기는 POSIX 파일 권한을 검사하며 Windows 시작을 거부한다.
상태 디렉터리는 절대 경로·비공개 권한(0700)이어야 한다. 읽기 키와 원천별 키는 서로 다른
32–4096자 ASCII 비밀값을 환경 변수로 제공한다. 명령행·URL에 키를 넣지 않는다.

최소 설정 예시다. 실제 설정과 자격은 Git 밖의 운영 경로에 둔다.

```yaml
collector_id: site-a-monitoring
site_id: site-a
readers:
  - principal_id: operator
    token_env: MONITORING_READ_TOKEN
    sites: [site-a]
sources:
  - id: host-local
    site_id: site-a
    kind: host_state
    path: /var/lib/rosy-host-state/status.json
```

설정 파일과 환경 변수를 준비한 뒤 실행한다.

```sh
rosy-monitoring --config /etc/rosy-monitoring/monitoring.yaml --state-dir /var/lib/rosy-monitoring
```

기본 수신은 `127.0.0.1:8786`이다. 원격 조회는 인증서를 검증하는 TLS 프록시를 거친다.
관제 PC의 사이트 스택 컨테이너만 `--host 0.0.0.0`으로 공개하지 않은 내부 망에서 받는다([D-936](../../docs/adr/D-936-monitoring-site-stack-service.md)).
`--port`는 1–65535, `--web-root`는 검증된 상태 화면 묶음의 경로다. 원천과 자격·상태 경로를
안전하게 준비할 수 없으면 `MONITORING_STARTUP_FAILED`로 종료하며 원문 예외·설정을 출력하지 않는다.
하나의 실행기가 등록 입력에 따라 개별 사이트, peer 통합 집계, peer 없는 중앙 직접 수집을 맡는다.
별도 중앙 프로세스가 종료돼도 개별 사이트 수집·조회는 계속된다. Fleet unit 의존성은 없다.

`MonitoringConfig`는 고정된 CORE·Fleet·host 보고 파일·서비스·peer 읽기 대상을 등록한다.
원천 URL의 자격·query·fragment를 거부하며 HTTPS 또는 리터럴 loopback HTTP만 허용한다.
`load_credentials`는 환경 변수 참조에서 읽기 principal과 상위 원천의 자격을 따로 읽는다.
읽기 principal마다 사이트 범위를 제한하고 reader/upstream 간 토큰 재사용을 거부한다.

`ObservationCache.update_local`은 검증된 로컬 관측을 게시한다.
`receive_peer`는 등록된 peer의 신원·사이트 집합·generation/sequence·시계를 확인한다.
`snapshot(sites)`는 지정한 등록 사이트의 노드·연결만 반환한다. HTTP principal의 접근 허용 검사는 호출자가 먼저 해야 한다.
스냅샷 조회는 원천을 조회하거나 로봇·호스트에 명령을 보내지 않는다.
Fleet가 재시작해 아직 캐시가 없으면 이전 로봇 관측을 보존하고 기존 보고 수명대로 만료시킨다.
유효한 캐시의 빈 목록은 실제 빈 관측 집합으로 반영한다. 로컬 저장·시각·재전송 거절을 원격 프로토콜 오류로 바꾸지 않는다.

원천 표본의 수명(`remaining_s`)과 수집 경로의 수명(`report_remaining_s`, 최대 15초)은 별개다.
기존 host 보고의 900/2100초 수명을 보존한다. 같은 표본을 다시 읽어도 원천 수명은 늘어나지 않는다.
수집이 끊기면 기존 건강 판정을 보존하면서 `stale`로 표시한다. 관측하지 못한 항목은 `unknown`이다.
peer 중계는 전송 시간과 시계 여유를 빼고 단조 시계로 만료를 계산한다. 재전송·역순·퇴역 generation·순환 집계를 거부한다.

항목이 누락되거나 `unknown`이 되어도 원래 표본 시각·만료 기한을 기억한다. 표본 이름만 바뀌어도 같은 관측 시각의 수명은 늘리지 않는다.
같은 capture 시각의 사실 내용 변경도 거부한다. 원천 시각의 정밀도가 낮아 실제 표본을 구분할 수 없으면 더 새로운 capture 시각을 기다린다.
최대 8192개 관측 ID를 기억하며, 한도에서는 새 ID를 거부하고 기존 관측을 계속 처리한다.
이보다 잦은 구성 요소 교체를 지원하려면 만료 anchor의 안전한 제거·운영 전환을 별도로 검증해야 한다.
캐시 조회·갱신은 하나의 소유자에서 직렬 호출한다. 수집기의 이벤트 루프가 이 역할을 맡는다.
서비스의 `MonitoringStore`는 정규화 관측·anchor·peer cursor를 SQLite에 먼저 저장한 후 캐시에 게시한다.
store를 열 때 OS 배타 writer lease를 획득하고 종료할 때 해제한다. 잠금 파일은 삭제하지 않는다.
같은 state DB를 여러 프로세스가 동시에 쓰지 못한다. 저장소를 교체·재초기화해 한도를 우회하지 않는다.
수신 프로세스 재시작은 원천 시각·판정을 유지하면서 경과 시간을 원천 수명에서 보수적으로 차감한다.
복구된 보고 경로는 stale이다. 손상·다른 소유자의 DB·시각 역행을 새 정상 상태로 초기화하지 않는다.
저장 실패 중에는 서비스의 비공개 snapshot이 고정 코드의 503을 반환한다.
상태 변경 이력은 사이트별 최대 4096건/7일이다. 원천 본문·주소·비밀값은 저장하지 않는다.
이전 등록까지 합해8192 anchor/64사이트 cursor를 보존한다. 더 큰 구성 전환은 운영 전환 검증이 필요하다.

`Collector`의 원천 수집은 5초 간격, 최대 동시 8개, 원천 요청당 3초다. GET은 캐시만 읽는다.
CORE는 viewer identity와 diagnostics, Fleet은 수동 monitoring 캐시, 호스트는 기존 status 파일을 읽는다.
일반 HTTP 정상 응답은 통신 성공이며, 서비스 자체 건강 판정은 UNKNOWN으로 유지한다.
파일 probe는 파일 조회 결과다. host-guard의 원격 연결 보고와 별도 링크로 표시한다.
파일은 로컬 regular file이어야 한다. 막힌 파일 I/O는 최대 8개만 보류하며 다음 순회에서 쌓지 않는다.
원격 파일시스템의 지연·프로세스 종료 영향은 실제 배포 환경에서 별도 수용해야 한다.

원격 시험은 [개발 안내](../../docs/reference/developer-guide.md)의 절차로 `operations/monitoring/test`를 실행한다.
설치 wheel 시험은 별도 임시 경로에서 빌드·설치하고 `python -I`로 namespace와 Fleet/ROS 비의존성을 확인한다.
이 시험은 실제 PC 네트워크·TLS 배치·장치·현장 수용을 대신하지 않는다.
