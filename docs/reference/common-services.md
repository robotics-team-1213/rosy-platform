# 공통 서비스 카탈로그

새 기능을 어디에 둘지 정할 때 이 문서를 먼저 본다. 공통 서비스는 여러 제품 앱이나 현장 전체에 같은 기능을 제공하고, 특정 앱의 업무 원장을 소유하지 않으며, 장치 명령 권한이 없다([D-987](../adr/D-987-common-services-catalog.md)).

여기 적혔다고 배포되거나 수용된 것은 아니다. 현재 상태는 각 모듈의 `progress.md`와 [STATUS](../../STATUS.md)에서 확인한다.

## 실행 서비스

자기 프로세스로 돌고 현장 Compose 서비스로 배치된다.

| 이름 | 소스 | Compose 서비스 | 맡는 것 | 맡지 않는 것 | 계약 | 결정 |
|---|---|---|---|---|---|---|
| Account | `operations/account` | `account`, `account-backup`, `account-backup-check` | 사람 신원·로그인 수단·권한·세션·회수·프로필 | 기계·장치·서비스 자격, 장치 admission, 조종 좌석, 앱별 허용 판단 | [Account 프로토콜](rosy-account-protocol.md) | D-757, D-807, D-962 |
| Monitoring | `operations/monitoring` | `monitoring` | 상태 수집·집계·읽기 API | 명령, host 복구 | [Monitoring API](rosy-monitoring-api.md) | D-876, D-936 |
| Media | `operations/site_ui/media` | `media`, `media-gateway` | 영상 세션 권한, 시청 요청, 미디어 프로세스 관리 | Fleet 영상 중계, 로봇 제어, CORE 장기 자격 수신 | [D-789](../adr/D-789-six-robot-webrtc-camera-transport.md) | D-789, D-801 |
| 현장 입구 | `deploy/site` | `proxy` | TLS 입구와 경로 전달 | 업무 판단, 계정 원장 | [site 배포 안내](../../deploy/site/README.md) | D-301, D-441 |

Account의 로그인·프로필·관리 화면 소스는 `applications/fleet/web`에, Monitoring 화면 소스는 `applications/monitoring`에 있다. 로봇 쪽 영상 송출 프로세스는 Media와 별도 패키지인 `middleware/media`다(D-791).

인증은 서비스마다 다르다. Account 로그인을 쓰지 않는 Monitoring 화면은 사람이 Monitoring 자체 읽기 키를 넣어 조회하고, Media는 짧은 미디어 위임을 검증한다.

## 공용 코드

자기 프로세스가 없다. 소비자와 함께 설치·컴파일되고, 수용은 그것을 싣는 런타임 모듈이 판정한다.

| 이름 | 소스 | 맡는 것 | 맡지 않는 것 | 결정 |
|---|---|---|---|---|
| Foundation | `contracts/foundation` | 프로토콜 스키마, 공유 계약, Account 클라이언트, 설정 불러오기 | 업무 절차, 산출물 저장 정책 | D-18, D-757, D-841 |
| 웹 공용 | `shared/web` | 디자인·컨트롤·통신 도구, 브라우저 세션 도구 | 사용자 업무, 전역 인증 상태 | D-939 |
| Android 공용 | `shared/android` | 피어 서명·TLS 고정·키 보관 도구, Account 세션 | 승인·자격 발급·명령 권한, 앱별 운전 세션, 카메라 자격 | D-939, D-987 |

## 공통 서비스가 아닌 현장 서비스

| Compose 서비스 | 이유 |
|---|---|
| `fleet` | 현장 조정과 Mission 원장을 소유한다 |
| `fleet-backup` | Fleet 상태의 백업이다 |
| `postgres` | Fleet만 쓰는 파생 문맥·로그 저장소다 |
| `vision` | 천장 영상에서 현장 관측을 만드는 업무 생산자다 |
| `control-unit-peer` | 관제 계층 연결에만 쓰는 peer 프록시다(D-850, D-960) |

## 새 기능을 넣을 때

1. 한 앱만 쓰면 그 앱에 둔다. 나중에 쓸지도 모른다는 이유로 옮기지 않는다.
2. 둘 이상의 앱이 같은 코드를 쓰면 공용 코드 위치에 둔다. 전역 utils 패키지는 만들지 않는다.
3. 자기 데이터와 수명이 필요하면 실행 서비스로 제안하고 ADR을 쓴다.
4. 현장 Compose에 서비스를 더하면 위 표 중 하나에 적는다. `test/architecture/test_common_services.py`가 확인한다.
5. 이름이 같아도 의미가 다르면 합치지 않는다. 사람 자격과 기계 자격을 합치지 않는다.
