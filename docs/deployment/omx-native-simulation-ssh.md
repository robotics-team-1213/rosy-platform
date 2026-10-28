# OMX native 시뮬레이션 SSH 배포

[D-786](../adr/D-786-omx-native-simulation-ssh-deployment.md)의 호스트 준비와 일반
배포 경로다. 개발 PC의 에이전트가 SSH로 실행한다. 사용자가 매번 원격 터미널에서
작업 명령을 입력하는 절차가 아니다. Docker는 사용하지 않는다.

## 호스트 준비

`private/lab-hosts.json`의 `sim_hosts`에 승인된 AI/model 대상을 역할과 함께 등록한다.
실주소와 계정은 공개 문서에 적지 않는다. site 역할·site marker가 있는 호스트는
시뮬레이션 대상이 아니다. 기존 SSH 키와 host-key 검증을 사용한다.

`deploy/robot/omx/native-sim-host.json.example`을 private 설정으로 복사하고 승인된
ROS setup, vendor overlay, JTC 의존 prefix, Python dependency 경로를 채운다.
배포기는 SDK를 새로 apt 설치하지 않는다. 플랫폼의 호스트 준비 절차로 마련한
ROS/Gazebo와 고정 vendor build를 검사하며, 빠진 입력은 실패로 반환한다.
Python은 시스템 `/usr/bin/python3`를 사용하여 OS protobuf 경로를 보존한다.

처음 한 번은 관리자 권한으로 제한된 `rosy-native-sim-control`을 provisioning해야 한다.
설치기는 root 소유 설정·anchor와 helper 전용 sudoers만 만든다. 일반 sudo나
systemd-run 전체를 무암호로 열지 않는다. 기존 `rosy-host-control`을 우회하지 않는다.
자동 provisioning은 실제 `sudo -n` 권한이 있을 때만 수행하며 암호를 받거나 저장하지 않는다.

관리자 설치용 입력은 커밋에서 읽은 helper/installer와 SHA-256 manifest로 보존한다.
설치 시 trusted inline bootstrap이 두 입력을 검증하고 root 전용 임시 디렉터리에
고정한 뒤 그 사본만 실행한다. 일반 계정이 바꿀 수 있는 staging 파일을 root로 실행하지 않는다.

## 배포와 실행

저장소의 커밋을 기준으로 실행한다. `<external-evidence-dir>`는 저장소 밖의 기록 경로다.

```text
python tools/remote/remote_omx_native.py deploy --host ai --config private/native-sim-host.json --log-dir <external-evidence-dir> --approve-host-provisioning
```

source는 git archive로 내보내므로 미커밋·추적되지 않은 코드는 포함하지 않는다.
SDK import·실제 G2 compile·module origin과 파일 해시를 검증한다. 준비 receipt와
provisioning 묶음은 기록 경로에, SDK 전체 manifest는 원격 staging에 보존한다.

helper가 없고 설치 권한도 없으면 `NEEDS_PROVISIONING`과 exit 3을 반환한다.
이는 배포 완료나 task 성공이 아니다. 관리자 provisioning 후 기존 receipt를 이어간다.

```text
python tools/remote/remote_omx_native.py provision --receipt <external-evidence-dir>/deployment.json --approve-host-provisioning
python tools/remote/remote_omx_native.py start --receipt <external-evidence-dir>/deployment.json --approve-isolated-simulation --approve-startup-home
```

배포는 팔을 움직이지 않는다. start의 두 허가는 시뮬레이션 실행과 startup에 대한
별도 허가다. 기존 G2 isolation guard·Fleet rearm/admission·UDS StopLocal·OMX owner를
통과한다. 실제 하드웨어 profile이나 수집 acceptance를 활성화하지 않는다.

서비스는 설정된 일반 계정으로 실행한다. AI 4 CPU/4 GB, model 8 CPU/6 GB,
최대 7,500초, private network/devices, read-only root/home과 고정 writable state를 쓴다.
서비스 시작 전 여유 CPU 6개·메모리 8 GB 기준과 기존 예약을 다시 검사한다.
기존 시험기의 예산 원장에는 이 run의 state 예산 파일 링크만 연결한다.

full SHA와 nonce는 unit·manifest·intent의 식별자다. state directory는 nonce만 써서
관제의 canonical UNIX socket path가 Linux 길이 제한 안에 들게 한다. hash 검증은
배포·재사용·시작에서 반복한다. 일반 계정에 대한 파일 시스템 불변성을 주장하지 않는다.

## 조회와 증거 수집

```text
python tools/remote/remote_omx_native.py status --receipt <external-evidence-dir>/deployment.json
python tools/remote/remote_omx_native.py fetch --receipt <external-evidence-dir>/deployment.json
```

각 fetch는 별도의 archive·추출 directory·SHA-256 receipt를 남긴다. 이전 관측 파일을
덮어쓰거나 삭제된 원격 파일과 섞지 않는다. 실행 중 수집은 파일별 관측이며 원자적인
전체 snapshot은 아니다. 서비스 ACK, SDK PASS, startup READY, task GOAL_CONFIRMED,
실물 episode 적격성, 학습 결과를 구분한다.

Linux 로그 이름은 Windows에서 저장할 수 있는 이름으로 변환한다. 원본 archive는
그대로 보존하며 `extraction-map.json`이 원본 상대 경로와 추출 경로를 연결한다.
최종 receipt의 archive·대조표 hash로 확인한다. 추출이 거절돼도 archive와
`archive-receipt.json`은 남는다. `g2/result.json` 등 짧은 소문자 경로는 유지한다.

시작 요청의 응답이 불명확하면 같은 run을 재시작하지 않는다. user intent와 root의
영속 intent를 조회해 복구한다. transient unit이 사라진 경우에도 root intent가 남는다.
별도 요청으로 수집한 SIM 데이터는 실제 시연 데이터가 아니다.
