## D-791 WebRTC 발행자와 사이트 미디어 권한 서비스를 독립 선택 설치 wheel로 둔다

**Status:** Accepted (2026-10-17, D-789 구현 범위의 소스 소유권 결정). 구현·장치·현장 수용을 뜻하지 않는다.

### Context

D-789는 별도 native 미디어 프로세스와 별도 사이트 영상 서비스를 결정했다. 첫 구현을 camera perception의 새 하위 폴더에 두자 D-766의 기존 `perception/front_camera/perception` 10,075줄 ratchet이 증가했다. 이 폴더는 인식 책임이며 네트워크 미디어 프로세스까지 보유할 이유가 없다. 이번 작업이 새로 추가한 영상 전송 코드만 독립 배포 단위로 옮긴다.

### Decision

1. 로봇 H.264·WHIP·capture watermark·후속 IPC 소비자는 `middleware/media/src/rosy_media_edge`에 둔다. 배포 단위는 optional wheel `rosy-media-edge`, native 서비스다. GStreamer는 해당 프로세스가 시작할 때만 불러온다. 기존 `control`/perception은 단일 카메라 소유와 관측 입력을 유지한다.
2. 사이트의 위임·세션·demand·감독 구현은 D-789 계획대로 `operations/site_ui/media/src/rosy_media`에 둔다. 배포 단위는 wheel `rosy-media`이며 Fleet distribution에 넣지 않는다.
3. 두 wheel은 `COLCON_IGNORE`, ownership manifest와 별도 크기 단위 및 harness 모듈로 등록한다. 기존 크기 상한·ratchet을 올리거나 검사 제외 목록을 추가하지 않는다.
4. 영상 위임 receipt의 ROS-free 데이터 모양은 `core_common.protocol.media_grants`에 둔다. CORE의 상태ful grant registry는 기존 `core_features.vision`에 남고, 서명·검증 DTO를 중복 소유하지 않는다.

| 결정 | 관계 |
|---|---|
| D-789 | 전달 방식·권한·예산·수용 기준 유지. 로봇 구현 폴더와 Python 내부 import만 이 기록으로 보완 |
| D-427 | middleware/operations/contracts 안의 독립 배포 책임이며 새 최상위 폴더 없음 |
| D-429 | 관심사는 other/통신 처리이며 Drive·Arm·Fleet 판단을 가져오지 않음 |
| D-430 | 최종 명령·정지 권한 없음. 안전 태그 변경 시 기존 독립 리뷰 절차 유지 |
| D-766 | 기존 초과 단위를 키우지 않고 실제 독립 프로세스를 새 standalone 배포 단위로 측정 |

### Consequences / Validation

이동 전 이번 작업의 파일을 참조하던 합성 loopback과 watermark/WHIP 시험을 새 경로로 갱신해 재실행한다. 외부 ROS·HTTP 계약은 바뀌지 않는다. native ARM64·기존 단일 카메라 IPC·운영 화면·서명 산출물·6대 현장 수용은 D-789 계획의 후속 gate로 남는다. 크기·소유권·harness 검사와 wheel 설치/import를 검증하며, 독립 wheel을 만들었다는 사실로 설치 완료를 주장하지 않는다.
