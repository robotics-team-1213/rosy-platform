## D-786 OMX native 시뮬레이션의 SSH 자동 배포와 제한된 호스트 실행 권한

**Status:** Proposed

### Context

D-770의 OMX 우선 수집·학습 준비 중 Docker 없는 Gazebo discovery와 SDK 검증은
통과했지만 실제 격리 task는 미실행이다. 일반 사용자 namespace 생성은 거절되며,
현재 무암호 관리 도구는 지정 서비스 관리만 허용한다. 실행 명령을 사용자에게 매번
전달하는 방식은 자동 운영이 아니다. 임시 경로와 수동 의존성 조합도 재배포 계약이 아니다.

### Decision

호스트 provisioning과 일반 release 배포를 나눈다. AI/model 호스트에만 root 소유의
`rosy-native-sim-control`을 설치한다. 설치는 관리자 권한이 실제로 있을 때 수행한다.
없는 권한을 우회하거나 기존 관리 도구의 allowlist를 임의로 넓히지 않는다.

helper는 root 소유 설정에서 역할·실행 계정을 읽는다. `probe`, 고정 형식 run ID의
`start/status/stop`만 받는다. 임의 명령·환경·경로·systemd 속성은 입력받지 않는다.
systemd가 namespace와 자원 제한을 만들며 실제 작업은 설정된 일반 사용자로 실행한다.
AI는 4 CPU/4 GB, model은 8 CPU/6 GB, 최대 7,500초다. private network/devices,
read-only root/home, no-new-privileges, control-group 정리와 재시작 금지를 고정한다.
site/Fleet 호스트에서는 설치·시뮬레이션 실행을 거절한다.

root 소유 `/var/lib/rosy-native-sim/<uid>/` 아래에 위치가 바뀌지 않는 release/state
좌석을 provisioning한다. 소스 release는 일반 계정이 배포하며, 서비스에서 state만
쓸 수 있다. 일반 시험 파일과 빌드는 기존 `~/rosy-test` 경로를 사용한다. 자원 원장의
기존 `~/rosy-jobs`에는 state의 예산 파일을 가리키는 소유 run의 링크만 연결한다.
이 경로는 호스트 provisioning의 관리 상태이며 로봇 설치나 현장 runtime이 아니다.

외부 개발 PC의 SSH 도구가 다음을 수행한다.

1. 승인된 lab host/역할과 커밋을 선택한다. 실주소와 SDK 경로는 private 설정이다.
2. 커밋 source와 고정 vendor/SDK 환경을 일반 권한으로 staging한다. 파일 해시와
   module origin, 실제 G2 compile/import 결과를 receipt에 남긴다.
3. helper 버전·역할·계정·고정 좌석을 조회하고 immutable release를 배포한다.
   helper가 없으면 검증된 provisioning 묶음과 `NEEDS_PROVISIONING` 결과를 만든다.
4. 명시적으로 승인된 시뮬레이션 실행만 요청한다. 인증·자원 부족은 시작 전 거절하며,
   시작 intent를 영속화한 뒤 helper에 한 번만 요청한다. 불명 응답은 조회로 복구한다.
5. 실제 서비스·READY·task 결과·정리 증거를 수집한다. 배포 성공, task 성공,
   실제 episode 적격성, 학습 완료는 서로 다른 결과다.

일반 배포는 관리자 암호를 받거나 기록하지 않는다. 원격 provisioning 권한이 없다면
정확히 차단 사실을 남기며, 이후 승인된 관리자 provisioning 한 번으로 같은 자동 경로를
이어간다. 일반 `sudo/systemd-run` 전체를 무암호로 열지 않는다.

G2의 isolation guard, 별도 startup 허가, Fleet rearm/admission, UDS StopLocal와
OMX owner는 유지한다. 배포나 helper 설치가 실물 profile 활성화·팔 Goal 허가는 아니다.
SIM 산출물을 실제 모방학습 데이터로 분류하지 않는다.

### 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | 호스트 provisioning은 deploy, 원격 요청은 tools, 학습 데이터는 learning에 둔다. |
| D-429 | source 위치와 설치·실행 호스트를 동일시하지 않는다. |
| D-430 | 기존 최종 명령 권한과 안전 경로를 유지하며 독립 리뷰로 변경 범위를 검증한다. |
| D-524 | 기존 관리 helper의 제한을 유지하고 시뮬레이션 권한을 별도 좁은 helper로 둔다. |
| D-568·D-571 | 여유 6 CPU/8 GB 기준, 예약 계산, site 제외, 호스트별 상한을 유지한다. |
| D-770 | 실제 수집·학습 완료 기준을 바꾸지 않고 반복 가능한 준비 경로를 제공한다. |

### Consequences

새 커밋 배포에 사용자 터미널 조작이 반복되지 않는다. 관리자 provisioning은 실제 OS
권한이 필요한 별도 단계로 남는다. 소스 테스트와 배포 receipt가 실제 격리 task 또는
실물 수용을 대신하지 않는다. 현재 실물 적격 episode는 0개이며 실물 학습은 미시작이다.
