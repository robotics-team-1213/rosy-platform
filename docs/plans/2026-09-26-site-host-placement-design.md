# 사이트 PC와 Pinky·OMX 실행 배치 설계

작성일: 2026-09-26
상태: [D-281](../adr/D-281-site-host-placement-and-omx-instance-isolation.md) 제안. 배치 모델이며 장치 구동·현장 승인 아님.

## 1. 배치의 기준

장비 수와 PC 수는 따로 정한다. Pinky는 로봇 안의 Pi/CORE가 실행 단위다. 고정 작업대 OMX-AI는 로봇별 제어 인스턴스가 실행 단위이고, 한 Ubuntu 워크스테이션이 한두 인스턴스를 호스팅할 수 있다. Fleet·천장 Vision·Caddy는 사이트 서비스이며, 같은 Ubuntu PC 또는 별도 PC에서 실행할 수 있다. 관제 브라우저는 서비스 설치 위치를 뜻하지 않는다. D-246에 맞춰 OMX의 현장 제어 런타임은 native systemd를 기본 후보로 둔다. 현재 OMX OCI 이미지는 장치 제어의 운영 승인이 아닌 개발·빌드·ROS-SIM 후보이다.

| 식별자 | 의미 | 예시 | 배치 변경 시 |
|---|---|---|---|
| `robot_id` | Pinky/CORE의 기존 로봇 정체성 | `rosy_01` | 유지 |
| `workcell_id` | 고정 OMX 작업대의 정체성 | `omx_01` | 유지 |
| `instance_id` | 그 장비의 단일 활성 제어 런타임 | `omx_01_control` | 이전 실행을 종료하고 새 배치 승인 |
| `host_id` | 설치된 물리 Ubuntu PC 또는 Pi | `site_pc_01` | 변경 가능 |
| 장치 ID | 실제 serial/camera의 영속 식별자 | 운영자 선택 `/dev/serial/by-id/...` | 새 호스트에서 재검증 |

`robot_id`와 `workcell_id`는 동일한 API 형식이라는 뜻이 아니다. 현행 Fleet `robots.yaml`은 CORE REST endpoint 목록이다. OMX 작업대 목록과 명령 계약은 실물 제어가 수용된 뒤 별도로 설계한다. 현재 단계의 인벤토리는 **배포·검증 기록**이지 Fleet에 새 명령을 여는 설정이 아니다.

## 2. 두 가지 지원 배치

```text
소형 현장:                                  분리 현장:
Pinky 1..N [Pi/CORE] ──TLS──┐              Pinky 1..N [Pi/CORE] ──TLS──┐
천장 폰 ──WSS───────────────┤              천장 폰 ──WSS───────────────┤
                             ▼                                           ▼
               Ubuntu site_pc_01                           Ubuntu site_pc_01
               Fleet + Vision + Caddy                      Fleet + Vision + Caddy
               OMX-01 인스턴스                              │
               OMX-02 인스턴스(선택)                       TLS / 수용된 계약
                             │                             ▼
                    로컬 serial/camera                  Ubuntu omx_pc_01
                                                       OMX-01 인스턴스
                                                       OMX-02 인스턴스(선택)
```

두 배치는 서비스 역할과 장비 ID가 같다. 하나의 물리 PC에서도 **사이트 Compose와 OMX별 native systemd 서비스**의 설정·비밀·로그·재시작 정책을 구분한다. Docker bridge를 PC 간 네트워크로 확장하지 않는다. 별도 PC의 OMX를 Fleet에서 제어하는 화살표는 아직 구현된 계약이 아니므로 이 그림의 TLS 선은 향후 수용된 workcell 계약만을 뜻한다.

최초 시험 후보는 소형 현장 배치다. 단, 현장 PC가 사이트·두 팔의 공통 장애 지점이 되는 점을 설치 심사에서 명시한다. 물리 거리, 전원 계통, 장애 격리 요구가 크면 측정 전부터 분리 배치를 선택할 수 있다.

## 3. 배포 인벤토리와 실행 규칙

인벤토리는 현장의 비밀 설정/배포 기록에 둔다. 아래는 **설계 예시**이며 현행 파서나 Compose가 읽는 파일이 아니다. 실제 주소, serial, token, 카메라 ID를 저장소에 넣지 않는다.

```yaml
site_id: example_site
hosts:
  site_pc_01:
    roles: [fleet, overhead_vision, omx_control]
workcells:
  omx_01:
    instance_id: omx_01_control
    host_id: site_pc_01
    # 장치별 follower/leader/camera identity와 calibration revision은 비공개 설정
  omx_02:
    instance_id: omx_02_control
    host_id: site_pc_01
```

배포 제어는 `(workcell_id, instance_id, host_id, native 산출물 digest, config revision, calibration revision, 실제 장치 식별자)`를 한 기록으로 묶는다. 한 작업대에 활성 인스턴스가 둘이거나, 한 serial 장치가 두 인스턴스에 할당되면 시작을 거부한다. 재부팅·USB 재열거 뒤에도 `ttyACM*` 번호로 추측하지 않고 by-id를 새로 해석한다. 카메라가 선정되면 같은 규칙으로 영속 ID와 프레임·보정 revision을 확인한다.

OMX는 인스턴스마다 하나의 명령 소유자를 갖는다. 리더 teleop, trajectory action, MoveIt/학습 정책의 동시 장치 점유는 허용하지 않는다. 같은 호스트의 두 vendor launch가 topic/action/TF/ROS graph를 섞지 않는지 ROS-SIM에서 확인한다. 사용될 RMW와 graph 격리가 검증되기 전에는 site/Fleet의 ROS graph와 연결하지 않는다. 현재 OMX Compose는 단일 비활성 개발 셸이므로 native 현장 서비스, 다중 인스턴스 구동, 자동 시작, 카메라 허가, 안전 정지는 **후속 구현**이다. 장치에 접근하는 운영 OCI를 원한다면 D-246을 명시적으로 재검토하고 실물 정지·복구 증거를 먼저 요구한다.

## 4. 호스트와 서비스의 자원·장애 경계

| 사건 | 기대 동작 | 확인할 증거 |
|---|---|---|
| 사이트 Fleet 또는 Vision 재시작 | Pinky 로컬 CORE와 OMX 로컬 제어의 정지·복구 경로 유지. 사이트 작업은 상태를 재조회 | 로봇 상태·사이트 task 이력, stale 표시 |
| OMX-01 제어 프로세스/serial 끊김 | OMX-01 HOLD, 명령 자동 재생 없음. OMX-02의 동작 영향 측정 | 장치별 action/stop 로그와 독립 readback |
| 공유 PC 전원·커널 장애 | 사이트·동거 OMX 전체 중단. 각 팔의 독립 물리 정지 및 재승인 필요 | 전원 상실, 복귀, 재시작 후 무명령 상태 |
| GPU 추론·학습 과부하 | 운영 제어와 Fleet의 시간/메모리 예산을 침범하지 않음. 추론 결과는 stale/degraded | 동시 부하의 지연·CPU/GPU/메모리 기록 |
| 장비를 다른 PC로 이전 | 이전 인스턴스 종료 확인 후 새 호스트 장치·보정·인증 재승인 | 한 시점 한 소유자, 배포 기록과 실제 프로세스 대조 |

서비스별 실행은 재시작·설정·장치 접근을 구분하지만 공통 PC 장애를 제거하지 않는다. 실제 부하 시험에서는 두 팔 동시 trajectory와 카메라 처리, 천장 Vision, Fleet 요청을 함께 실행한다. 수용 지표는 제조사 제어 주기, 실제 정지/응답 요구와 현장 작업 시간에서 정하고 계측한다. 이 설계에서 임의의 허용 지연 수치를 만들어 통과시키지 않는다.

## 5. 네트워크와 권한

1. Pinky CORE는 각 Pi의 native 서비스다. Fleet은 로봇별 인증 REST/WSS 계약으로 상태를 읽고 원자 명령을 제출한다. 접수와 완료는 구분한다.
2. 천장 폰은 사이트 Vision ingress에 WSS로 프레임을 보낸다. Vision은 영상에서 관측값을 만들고 Fleet에는 현재 수용된 작은 파생 결과만 보낸다.
3. OMX의 작업 카메라 원본, ROS graph, serial 장치는 해당 작업대 제어 호스트에 머문다. 원격 workcell 상태·작업 요청이 필요해질 때는 D-273의 실물 검증 뒤 별도 버전 계약과 인증·명령 결과·정지 절차를 정의한다.
4. 향후 GPU PC는 Vision 연산 서비스를 옮겨 받을 수 있다. 그 호스트는 팔이나 바퀴에 직접 명령할 권한을 갖지 않는다. 운영 추론과 오프라인 학습은 자원·배포 주기를 나눈다.
5. 각 호스트는 고유 이름, TLS 신뢰, 이미지 digest, 비밀, 방화벽 규칙과 재시작 절차를 가진다. Compose 프로젝트 이름은 호스트 안의 구분이며 네트워크 전체의 장비 정체성이 아니다.

## 6. 구현·검증 순서와 분리 기준

| 단계 | 작업 | 통과 범위 |
|---|---|---|
| A. 배포 계약 | 인벤토리 스키마와 중복 ID/장치 거절, 인스턴스별 native 서비스/제품 산출물 pin. OMX OCI의 운영 사용 여부는 D-246과 별도 결정 | SOURCE/LOCAL |
| B. 이중 graph | 동일 호스트에서 OMX 두 인스턴스의 분리된 action/topic/TF·RMW, 한 인스턴스 종료가 다른 인스턴스에 주는 영향 | ROS-SIM |
| C. 단일 실물 | 첫 OMX의 serial, camera, 제어/정지/전원 상실, 보정과 복구 | DEVICE |
| D. 두 실물 동시 | 두 OMX와 사이트 서비스의 동시 동작, USB·CPU/GPU·열·지연, 한 장치 장애 | DEVICE/SITE |
| E. 운용 배치 | 공유 호스트 중단·백업·재기동, 호스트 이전 연습, 실제 작업 결과 | FIELD |

다음 중 하나가 확인되면 OMX 인스턴스를 별도 호스트로 옮긴다: 동시 부하가 제어/정지 요구를 만족하지 못함, 장치가 독립적으로 연결·복구되지 않음, 물리 설치 거리가 USB/카메라 연결 범위를 벗어남, 공통 PC 장애가 허용되지 않음. 한 PC의 사이트 서비스와 OMX를 분리할지, OMX 두 대를 서로 분리할지는 실패 원인에 따라 결정한다.

현재 SOURCE/LOCAL 문서·Compose 검사는 다중 OMX의 장치 동작을 입증하지 않는다. `omx.enabled: false`를 유지하고, Pinky+OMX 이동 조작은 D-55/D-71의 별도 단계로 둔다.

## 근거

- [D-273 OMX 제어·영상 순서](../adr/D-273-omx-camera-stream-and-arm-control-order.md)
- [D-275 웹·Vision 소유권](../adr/D-275-web-surface-and-video-runtime-ownership.md)
- [OMX 워크스테이션 실행 계획](2026-09-26-omx-ai-workstation-runtime.md)
- [사이트 배포 설명](../../deploy/site/README.md)
- [OMX 배포 설명](../../deploy/omx/README.md)
- [D-246 native 제어 결정](../adr/D-246-runtime-flexibility-native-default-container-sidecar-lane.md)
