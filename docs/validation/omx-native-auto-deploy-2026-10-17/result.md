# OMX native SSH 자동 배포 검증

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 최종 집중 검증 commit `716d0f912d`.
실제 AI PC staging 검증 commit `8e501ed953`.

## 결과

에이전트가 승인된 SSH 경로로 직접 source staging, SDK 검증, provisioning 권한 조회,
상태 조회와 두 번의 독립 증거 회수를 수행했다. 사용자에게 원격 task 명령을 매번
실행하도록 전달하는 방식은 일반 배포 경로에서 제거했다.

소스는 커밋의 git archive이며 source 8,264개 파일과 SDK 의존 55,672개 파일을
검증했다. 실제 G2 compiler, SDK Python imports와 source module origins는 PASS다.
이 검사는 ROS 초기화·Gazebo 기동·Goal 제출을 하지 않는다.

제한된 root helper는 설치되지 않았으며 일반 `sudo -n`은 관리자 인증을 요구했다.
자동 provisioning 결과는 `NEEDS_PROVISIONING`, `attempted_install=false`다.
관리자 설치 입력 두 개와 commit/해시 manifest, 대상 경로·권한의 dry-run JSON을 준비했다.
호스트의 sudoers·root 설정·namespace를 변경하지 않았다.

## 소프트웨어 검증

노트북 pytest는 실행하지 않았다. 커밋 기반 remote_pytest의 Model/Fleet 시험 호스트에서
실행했으며, 마지막 집중 묶음은 **70 passed, skip 없음**이다.

| 범위 | 수정 전 | 수정 후 |
|---|---:|---:|
| 좁은 root helper·installer | 누락 21 failed | 기존 25 passed |
| source/SDK/activation/runtime | 누락 13 failed | 초기 13 passed |
| 역할·activation·명시적 허가·중복 시작·불명 응답 | 누락 15 failed | 기존 15 passed |
| 시작 직전 site/자원·SDK 재사용·복사 중 변조·예약 계산 | 5 failed, 15 passed | 최종 포함 |
| trusted root bootstrap | 누락 2 failed | 전체 CLI 17 passed |
| compact UDS 경로와 다른 실행 release 거절 | 2 failed | 최종 포함 |
| 상태·회수의 성공 exit와 차단 상태 구분 | 2 failed | 최종 포함 |
| 최종 helper/runtime/SSH CLI | — | **27 + 23 + 20 = 70 passed** |

실제 helper 소스의 run ID guard를 제거한 복사본과 PrivateNetwork를 끈 복사본에서
기존 회귀가 실패했고, 원상 복구 후 통과했다. 원본 파일은 바꾸지 않았다.
이 mutation 검증은 원격 pytest 임시 파일에서만 수행했으며 root·ROS를 실행하지 않았다.

독립 리뷰가 발견한 root 설치 입력의 TOCTOU는 로컬 커밋 bytes를 포함한 trusted inline
bootstrap으로 보완했다. root가 두 digest를 먼저 확인하고 root 전용 임시 디렉터리에
고정한 사본만 실행한다. 일반 계정이 바꿀 수 있는 staging Python을 root로 실행하지 않는다.

기존 canonical OMX UDS 경로는 긴 state 이름에서 125 bytes로 실패했다. full run ID는
unit·manifest·intent에 유지하고 state directory만 nonce로 줄여 84 bytes로 만들었다.
원격 Linux에서 생성한 compact 경로의 실제 AF_UNIX bind를 시험했다. release가 다른
native job 코드도 child 시작 전에 거절한다.

증거 회수는 매번 별도의 raw archive·추출 directory·SHA-256 receipt를 보존한다.
삭제된 파일이 다음 회수에 남지 않는 회귀와 실제 AI PC의 두 별도 archive를 확인했다.
실행 중 회수는 원자적인 전체 snapshot이 아닌 관측이다.

독립 `/root/review_native_cycle`와 `/root/review_topic_task`의 최종 재검토에서
남은 material finding은 없었다. root provisioning 승인 범위는 실제 OS 권한이 있을
경우의 제한된 설치이며, 설치나 runtime 수용이 실행됐다는 뜻은 아니다.

## 원본과 범위 제한

원본은 외부 scratch `native-auto-*` 기록이며 주요 묶음은 `native-auto-final-green`,
`native-auto-helper-compact-green`, `native-auto-deployment-2`다. 실제 주소·계정과
전체 manifest·archive는 private 운영 기록에 보존하고 공개 문서에 넣지 않는다.

**미실행:** root helper 실제 설치, 새 고정 release 좌석 활성화, 격리 G2 startup·task,
실물 owner 활성화·변위·정지 수용, 실제 시연 수집·모델 학습. 실제 적격 episode는 0개다.
기존 G2 guard와 Fleet/OMX 명령 권한을 바꾸지 않았으며 SIM 데이터는 실물 데이터가 아니다.

절차: [SSH 자동 배포](../../deployment/omx-native-simulation-ssh.md),
설계: [D-786](../../adr/D-786-omx-native-simulation-ssh-deployment.md).
