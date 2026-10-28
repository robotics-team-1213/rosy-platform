## D-901 Native workcell observation communication isolation

**Status:** Accepted (2026-10-28). 사용자 요청으로 실제 ROS 통신 경계를 격리한다. 소스 결정이며 현장 전환 수용은 별도다.

### Context

OMX 카메라 수집기, 수동 관측기, 미리보기와 Fleet/Vision 브리지가 같은 호스트의 ROS Image/JointState로 연결돼 있었다. localhost DDS도 ROS 통신이며, 사용자가 요구한 영상 ROS 경유 금지와 맞지 않는다. D-136의 같은 호스트 raw DDS 허용은 이 운영 경로에서 폐기한다.

### Decision

- 카메라 → 미리보기/브리지와 수동 관절 관측기 → 미리보기/브리지는 ROS 없는 같은 사용자·호스트의 최신 스냅샷으로 연결한다. 카메라당 V4L2 소유자 하나, 기존 읽기 전용 serial 소유자 하나를 유지한다. 영상은 원본에서 화질을 측정한 후 JPEG로 한 번 인코딩한다.
- systemd의 `%t/rosy-observations`는 재부팅 때 사라지는 사용자 런타임 공간이다. 소스별 원자 교체 파일 하나, JPEG 최대 1 MiB와 헤더 최대 16 KiB로 보관량을 제한한다. 독자가 느려도 생산자에 큐를 쌓지 않는다. 녹화는 별도 recording owner와 명시적인 장치 인계를 사용한다.
- 기존 manifest의 `image_topic`·`joint_topic`, CLI의 `--topic`·`--joint-topic`은 이전 등록과의 대응을 위한 불투명한 로컬 키다. 이 entry point들은 ROS를 시작하거나 토픽을 발행·구독하지 않는다. 키 이름 변경과 외부 manifest 개정은 이번 전환의 필수 조건이 아니다.
- 원본 wall-clock 수집 시각과 같은 호스트 monotonic 시각을 유지한다. 두 시계 중 어느 것이든 2초를 넘거나 미래 허용치를 벗어나면 폐기한다. 파일을 재조회해도 새 수집 시각으로 바꾸지 않는다. 잘못된 파일·단절은 stale로 표시하며 ROS fallback은 없다.
- 외부 연결은 기존 인증된 HTTPS Fleet 관측 ingress와 WSS Vision ingress를 유지한다. TLS, 소스별 자격 증명, sequence와 재연결 정책을 우회하지 않는다. Fleet는 영상 bulk relay가 되지 않는다.
- CORE의 최종 Base 명령 소유권(D-1·D-2), OMX의 별도 joint/action 소유권은 유지한다. ROS가 필요한 장치 드라이버·Nav2·시뮬레이터는 명시적인 adapter 경계에 둔다. 이 수정은 나머지 로봇/시뮬레이터 경로까지 전환됐다는 증거가 아니다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 deploy composition과 foundation의 stdlib helper를 사용하며 새 최상위 part를 만들지 않는다. |
| D-429 | 관측 producer와 consumer의 실제 파일 IPC 연결을 변경한다. Fleet/World/Decision 책임은 바꾸지 않는다. |
| D-430 | 관절 값의 모델·torque-OFF·고장·250 ms 읽기 검사를 보존한다. 관측 경로는 명령 권한을 부여하지 않는다. |

### Consequences

전환은 카메라·viewer·observer·bridge를 같은 버전으로 적용해야 한다. 기존 DDS 전용 collection/simulator adapter는 이 카메라에서 더 이상 영상을 받지 못하며, 기존 장치 소유자를 중지하고 native 입력을 선택하거나 별도 adapter로 검증해야 한다. 실행 중 recording/chunk owner는 건드리지 않는다.

사용자 drop-in의 ExecStart, 서로 다른 runtime 디렉터리, 각 등록 키의 일치를 먼저 확인한다. updater의 idle gate와 rollback을 유지하고, 전환 뒤 선택된 소스별 advancing frame·fresh 관절·TLS 전송을 확인한다. 실패하면 해당 관측 소비를 중지하고 검증된 이전 release/unit/env 세트를 함께 복구한다. 이전 release의 ROS 영상 경로는 새 정책 수용 상태가 아니므로 격리된 정비 환경에서만 사용한다.

원격 단위·통합 시험은 소스 근거다. 실물 화질·노출 동기화·모터 안전 수용·WebRTC 성능 또는 전체 플랫폼 ROS 제거로 확대 해석하지 않는다.
