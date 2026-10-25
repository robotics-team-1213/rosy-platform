## D-862 관제 정보 집계와 관제별 결과를 보존하는 정지 요청

**Status:** Accepted for implementation (2026-10-24, 사용자의 각 관제 정보 수집·실제 통합관제 구현 지시). 구현·원격 회귀·배포·장치·현장 수용은 각각 증거로 판단한다.

### Context

D-850의 동일 관제 단위와 D-855의 영속 navigation 위임은 독립·중첩 구성을 지원하지만 하위의 상태·직접 로봇·작업·지도를 집계하지 않는다. 부모가 소유하지 않은 장치의 주소·자격을 받거나 현재 관측을 실행 완료로 덮어쓰는 방식으로 통합할 수 없다. 서로 다른 관제의 같은 map ID도 공유 좌표계를 증명하지 않는다.

기존 Fleet 전체 정지는 dispatch latch, Console의 로봇·신호·대형 정리, 같은 host OMX 국소 정지, queue 정리를 함께 수행한다. navigation 위임 취소나 Console.estop_all만으로 이 경로를 대체할 수 없다. CORE와 OMX의 기존 stop 수신기는 늦은 요청을 현재 세대로 거절하는 계약이 없으므로 부모 HTTP 응답 유실 뒤 자동 재발행은 재무장 이후의 작업을 다시 멈출 수 있다.

### Decision

API reference v1.309에 아래 additive 계약을 등록한다. canonical wire export는 `core_common.protocol.schemas`, 모델 정의는 별도 `protocol/integrated_control.py`가 소유한다. Envelope/WS protocol_version은1.0으로 유지한다.

| 표면 | 책임·권한 |
|---|---|
| `GET /api/fleet/control-unit/overview` | 관제별 제한된 요약·직접 로봇/미완료 Task 개수·지도 식별·현재 dispatch fence·신선도·미확인 정지 개수 |
| `GET /api/fleet/control-unit/units/{unit_id}` | 선택 관제의 직접 로봇 상태·최대100개 Task 최소 요약 |
| `GET /api/fleet/control-unit/units/{unit_id}/map` | 선택 관제의 활성 지도 식별/version과 장소·차로 geometry |
| `POST /api/fleet/control-unit/stops` | 기명 로컬 운영자가 고정 identity와 관제별 expected fence로 subtree 정지 요청 생성 |
| `POST /api/fleet/control-unit/stop-inbox` | 명시적으로 허용된 직계 부모 서비스만 같은 정지 요청을 중계 |
| `GET /api/fleet/control-unit/stops` | 로컬 사람 viewer가 최대100개 stop 메타데이터 조회. 부모 서비스에는 전체 원장을 공개하지 않음 |
| `GET /api/fleet/control-unit/stops/{origin}/{stop_id}` | 같은 정지 요청의 관제별 응답·미확인 결과 조회. 조회는 실행하지 않음 |
| `POST /api/fleet/control-unit/stops/{origin}/{stop_id}/reconcile` | 해당 관제의 기명 로컬 운영자만 전송 종료·receiver 재시운전 확인을 기록. 재무장·정지 해제는 하지 않음 |

#### 정보 소유와 신선도

각 관제는 자기 직접 자원만 생산한다. 부모는 고정된 직계 이웃을 호출하고 자식이 보고한 subtree의 unit/parent/resource 범위와 구성 revision을 검증한다. sibling·임의 endpoint·역방향 전체 원장 조회는 허용하지 않는다. 기존 부모 service 자격만으로 새 정보·정지 권한을 자동 부여하지 않는다. `share_information_with_parent`, `accept_parent_stop`은 각각 strict bool·기본false이며 승인된 배치에서 별도로 켠다.

overview는 최대64개 unit 요약, detail은 최대256개 직접 로봇·100개 Task다. 응답은 유한 JSON128KiB 이하이고 전체 지도 geometry는 별도2MiB 이하 경로로 나눈다. 각 지도는 기존 SiteMap의500 places·1000 lanes·전체20000 points를 넘지 않는다. map/element ID는 기존 SiteMap 제약을 재사용하고 관제 ID로 잘못 좁히지 않는다.

기존 SharedGather를 통해 관측을 재사용하며 별도 console.snapshot 호출로 traffic·handoff를 중복 실행하지 않는다. 수집 시각은 aware datetime, 신선도는 source age와 수신 후 monotonic 경과로 판단한다. 미완료 관측은5초 기준으로 stale이며 단절을 성공으로 바꾸지 않는다. 한 이웃 실패가 다른 이웃의 결과를 지우지 않는다. 센서별 pose/battery/safety evidence의 fresh/delayed/disconnected/unavailable/unknown을 유지하고 미관측 기본값을 실측값으로 채우지 않는다.

Task는 직접 소유 robot ID를 SQL에서 먼저 제한한 최소 작업/로봇 ID·상태·시각만 공유한다. actor·request·evidence·reason과 개인 Mission/Cell Job 자료는 이 계약으로 노출하지 않는다. 지도는 `(owner_unit,map_id,version,unit_local)` 출처를 보존한다. 변환 근거 없는 관제 간 좌표 overlay나 상위의 최종 장치 명령은 만들지 않는다.

#### 정지 요청의 영속 identity와 실행 경합

정지 identity는 `(origin_unit,stop_id)`이며 target subtree·구성 revision·관제별 기존 authority_epoch/generation을 canonical body로 고정한다. caller가 사람 actor·임의 URL·장치 자격을 제공하지 않는다. 부모 ingress는 직계 부모와 ancestor origin·대상 범위를 검증한다.

각 대상 관제는 동일 SQLite transaction에서 identity/본문 중복, expected fence, stop 기록과 기존 dispatch latch mutation을 결속한다. 같은 요청은 같은 결과를 반환하며 재무장 이후 늦게 처음 도착한 과거 fence도 거절한다. relay 관제는 대상에 속하지 않으면 자기 장치를 정지하지 않는다.

commit 이후에는 기존 전체 로컬 정지 경로를 한 번 실행한다. 활성 send task와 불확실한 결과를 영속 guard로 추적하고 같은 rearm transaction에서 차단한다. handler 취소 후 살아 있는 OMX thread도 send 종료로 취급하지 않는다. 응답 유실·재시작·polling은 정지를 다시 발행하지 않는다. 조회로 이미 전달된 자식 기록을 대조할 수 있지만 미전달 요청을 자동 POST하지 않는다.

typed 통합 정지는 journal/fence를 확보하지 못하면 새 fanout 없이 JOURNAL_UNAVAILABLE/UNKNOWN으로 남긴다. 기존 사람이 호출하는 `/api/fleet/estop`의 즉시 best-effort 정지와 DB 장애 예외 처리는 그대로 유지한다. 두 경로를 같은 실패 fallback으로 합쳐 과거 원격 요청이 새 작업을 멈추게 하지 않는다.

결과는 관제별 ACKNOWLEDGED/PARTIAL/UNKNOWN/STALE_FENCE/NOT_REACHED 등을 보존하고 robot 응답 개수·OMX latch 응답·원래 dispatch fence를 구분한다. `physical_stop`은 UNVERIFIED다. HTTP200, CORE estop:true, 기존 stopped:true, LOCAL_LATCHED를 물리 정지·claim 해제로 해석하지 않는다. 실제 장치 확인과 현장 정지 수용은 별도다.

#### 미확인 결과의 복구

UNKNOWN을 현재 속도·과거 receipt·Fleet 재시작만으로 해제하지 않는다. 해당 관제의 기명 운영자가 기존 전송 연결을 종료하고 영향 receiver를 재시운전한 뒤 exact stop ID·현행 generation·영향 unit과 확인 근거를 기록한다. 살아 있는 send를 이 확인으로 덮어쓸 수 없다. 확인 가능한 owner runtime identity는 확인하되 없는 증거를 만들어내지 않는다.

처분은 SUPERSEDED_BY_OPERATOR_RECOMMISSIONING으로 원래 UNKNOWN과 운영자 근거를 보존한다. 이는 delivery uncertainty guard의 처분이며 기계적인 물리 정지 증명이 아니다. CORE admin release, OMX recovery, 기존 Fleet 기명 rearm과 미해결 Action claim 검사는 별도다. 상위 서비스는 하위의 확인·release·rearm을 대신하지 않는다.

#### TLS와 배치

peer URL은 기존 고정 origin을 사용한다. `tls_ca_file`은 명시적 신뢰 파일이며 hostname·인증서 검증, redirect 거절, 환경 proxy 미사용을 유지한다. 실제 TCP/TLS 회귀로 신뢰/불신 인증서를 구분한다. 단독 CLI와 opt-in site 배치에 설정·수신 service principal·송신 token·CA mount를 연결한다. 실제 주소·자격은 승인된 private 위치에 두며 이 계약이 배포나 장치 운행을 실행하지 않는다.

### Consequences and verification

기존 owner와 원장을 유지한 채 실제 관제 정보가 상위까지 전달된다. 그 대가로 지도 좌표계는 소유 관제별로 표시하고, 통합 정지는 원격 물리 E-stop이나 자동 복구를 보장하지 않는다. 연결 복구로 권한·정지 해제·재무장을 자동 승격하지 않는다.

wire strictness·크기/소유 범위·신선도·권한/개인정보, R/A/B/A1 수집과 한 자식 장애, TLS 신뢰 실패, stop 중복/응답 유실/재시작/재무장 경합·DB 장애·살아 있는 send·로컬 재시운전 확인을 회귀한다. 프론트·sample·실제 HTTP/TCP/TLS·합성 CORE/OMX 경로의 source SHA와 실행 결과를 별도로 남긴다. 이 ADR 등록만으로 runtime·화면·현장 완료를 표시하지 않는다.

### 관제별 정지 범위 배정의 구체화

immutable body는 각 관제에 최초 배정된 projection이다. origin_id/stop_id/config_revision은 같게 유지한다. 대상이 자기 관제이면 각 직접 자식에게 target_unit을 그 자식으로, expected_controls를 그 자식 subtree의 기존 fence로 제한한다. 대상이 더 깊은 관제이면 해당 next hop으로 같은 target을 전달한다. 부모가 원래 전체 의도를 보존하고 각 관제는 자기에게 배정된 범위만 기록·실행하므로 sibling의 fence나 결과를 전달하지 않는다.

자식 projection은 최초 전송 전에 고정·저장한다. 같은 identity의 다른 projection은 충돌이며 재시도·재연결에서 새 fence를 보충하지 않는다. 부모는 자식 snapshot의 target/result unit을 저장한 배정 범위와 검증한다. 원문 전체가 동일해야 하는 navigation delegation helper로 이 검증을 대체하지 않는다. 필터 뒤 fence가 없는 자식은 POST하지 않고 NOT_REACHED/UNKNOWN으로 보존한다. 조회도 같은 배정 범위로 제한한다. 실제 중첩·targeted relay·빈 fence·사칭/중복 회귀로 확인한다.

### 착지 통합의 reference 버전

초기 구현 브랜치에서 선점·검증한 v1.309 뒤에 main의 v1.310이 먼저 착지했다. 해당 계약을 보존하고 새로 선점한 **v1.313**에 이 ADR의 동일 wire를 통합한다. API reference·9개 현재 버전 pin·자기 changelog 제목/행을 공식 도구와 함께 정렬하며, 위 모델·권한·실행 범위 결정은 바꾸지 않는다. 초기 RED/GREEN의 v1.309 source와 최종 통합 source를 검증 기록에서 구분한다.

### 구현 결속: 전용 자격과 실제 직접 장치 목록

`role: service`, `principal_id: control-unit:<이웃>`은 모든 HTTP method에서 정확한 `/api/fleet/control-unit` namespace만 호출한다. 일반 Fleet read/proposal 경로로 우회해 raw Task의 actor/request/evidence를 읽거나 Cell Job 후보를 쓰지 못한다. namespace 안에서도 기존 직계 이웃·ancestor·배정 범위·opt-in·기명 사람 검사를 적용한다. 일반 Cell service와 사람의 기존 권한은 유지한다.

송신 토큰은 각 이웃 사이에서 다르고, 모든 로컬 수신 principal·Console·로봇 REST·CORE Agent pairing 자격과도 달라야 한다. `Accept-Encoding: identity`만 사용하고 압축 응답은 읽기 전에 거절한다. 요청 전체 3초와 JSON byte 상한을 지키며, 이 시간은 물리 정지 보장 시간이 아니다.

typed stop 설치 시 실제 `Console.robot_ids`와 manifest의 직접 `robot:` 목록이 정확히 일치해야 한다. configured OMX의 각 workcell은 자기 관제의 `workcell:<id>`, 설정된 신호등은 `signal:<id>` 자원이어야 한다. `signal:`은 topology의 직접 소유 표기이며 admission resource kind를 추가하지 않는다. 기존 topology의 중복 소유 거절을 사용하며 누락·타 관제 소유를 시작 시 거절한다. 각 인스턴스의 DB를 공유하지 않는다.

조건부 정지는 journal/fence/latch의 같은 transaction이 성공한 최초 ticket만 장치 경로로 보낸다. SQLite 실패를 새 무조건 정지로 대체하지 않는다. 기존 로컬 사람 E-stop의 DB 장애 시 best-effort 경로는 유지한다. 공통 장치 callback은 Console·OMX의 실제 작업이 모두 끝나기 전에 반환하지 않는다. 요청 취소는 owned 작업을 취소하지 않으며, 종료는 그 작업을 drain한 뒤 peer client를 닫는다. 재시운전 확인도 owned 작업이 live-work gate를 유지하고 실제 thread 완료까지 기다린다.
