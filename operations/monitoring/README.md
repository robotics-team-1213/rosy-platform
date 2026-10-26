# ROSY Monitoring

ROSY 시스템 모니터링의 독립 Python wheel은 `rosy-monitoring`, import는 `rosy.monitoring`이다.
소유권과 배치 결정은 [D-876](../../docs/adr/D-876-rosy-monitoring-independent-site-and-aggregate.md)을 따른다.

현재 구현은 관측 모델, 읽기 전용 설정·자격 검증, 사이트별 그래프 캐시다.
HTTP 수집기·조회 API·상태 화면·native 배포는 후속 구현이다. 실행 중인 Fleet 프로세스나 ROS를 import하지 않는다.

저장소 루트에서 wheel을 설치한다.

```sh
python -m pip install ./contracts/foundation ./operations/monitoring
```

`MonitoringConfig`는 고정된 CORE·Fleet·host 보고 파일·서비스·peer 읽기 대상을 등록한다.
원천 URL의 자격·query·fragment를 거부하며 HTTPS 또는 리터럴 loopback HTTP만 허용한다.
`load_credentials`는 환경 변수 참조에서 읽기 principal과 상위 원천의 자격을 따로 읽는다.
읽기 principal마다 사이트 범위를 제한하고 reader/upstream 간 토큰 재사용을 거부한다.

`ObservationCache.update_local`은 검증된 로컬 관측을 게시한다.
`receive_peer`는 등록된 peer의 신원·사이트 집합·generation/sequence·시계를 확인한다.
`snapshot(sites)`는 지정한 등록 사이트의 노드·연결만 반환한다. HTTP principal의 접근 허용 검사는 호출자가 먼저 해야 한다.
스냅샷 조회는 원천을 조회하거나 로봇·호스트에 명령을 보내지 않는다.

원천 표본의 수명(`remaining_s`)과 수집 경로의 수명(`report_remaining_s`, 최대 15초)은 별개다.
기존 host 보고의 900/2100초 수명을 보존한다. 같은 표본을 다시 읽어도 원천 수명은 늘어나지 않는다.
수집이 끊기면 기존 건강 판정을 보존하면서 `stale`로 표시한다. 관측하지 못한 항목은 `unknown`이다.
peer 중계는 전송 시간과 시계 여유를 빼고 단조 시계로 만료를 계산한다. 재전송·역순·퇴역 generation·순환 집계를 거부한다.

항목이 누락되거나 `unknown`이 되어도 원래 표본 시각·만료 기한을 기억한다. 표본 이름만 바뀌어도 같은 관측 시각의 수명은 늘리지 않는다.
같은 capture 시각의 사실 내용 변경도 거부한다. 원천 시각의 정밀도가 낮아 실제 표본을 구분할 수 없으면 더 새로운 capture 시각을 기다린다.
한 프로세스에서 최대 8192개 관측 ID를 기억하며, 한도에서는 새 ID를 거부하고 기존 관측을 계속 처리한다.
이보다 잦은 구성 요소 교체를 재시작 없이 지원하려면 영속화된 제한형 anchor가 필요하다.
캐시 조회·갱신은 하나의 소유자에서 직렬 호출한다. 수집기의 이벤트 루프가 이 역할을 맡는다.
현재 anchor 보존 범위는 캐시 인스턴스 수명이다. 수신 수집기 프로세스 재시작 후의 복구는 후속 SQLite·서비스 연동과 수용 시험이 필요하다.

원격 시험은 [개발 안내](../../docs/reference/developer-guide.md)의 절차로 `operations/monitoring/test`를 실행한다.
설치 wheel 시험은 별도 임시 경로에서 빌드·설치하고 `python -I`로 namespace와 Fleet/ROS 비의존성을 확인한다.
이 시험은 실제 PC 네트워크·TLS 배치·장치·현장 수용을 대신하지 않는다.
