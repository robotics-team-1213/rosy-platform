# OMX native helper 설치·첫 실행 전 검증

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 이전 [배포 준비 기록](../omx-native-auto-deploy-2026-10-17/result.md)의
관리자 설치 이후 후속 관측이다. 이 기록의 범위는 설치·activation·실행 전 검사다.

## 설치와 배포

사용자가 초기 관리자 설치 완료를 알린 뒤 에이전트가 승인된 SSH 경로에서
`sudo -n /usr/local/sbin/rosy-native-sim-control probe`를 직접 실행했다.
exit 0, schema `rosy.native-sim-control/1`, role `ai`, 일반 계정 uid/gid 1000,
고정 state root, CPU 4개·메모리 4 GB·최대 7,500초 설정을 확인했다.
기존 일반 sudo 권한을 확대하지 않고 helper 전용 경로를 사용했다.

커밋 `8e501ed953`의 기존 준비 receipt를 이어 activation이 `READY`가 됐다.
첫 reserve는 빈 `.native-sim-placement.lock`을 자원 예산으로 해석해 실패했다.
Python glob은 숨김 파일도 포함하므로 canonical Bash 예산 glob과 달랐다.
실패는 user/root start intent와 서비스 시작 전이며 Goal은 제출되지 않았다.

커밋 `9b760dce01`은 숨김 advisory lock을 제외하고,
보이는 다른 작업의 예산과 잘못된 예산 거절을 유지한다. 독립 리뷰에서 이 변경은
canonical 배치 검사와 일치함을 확인했다. 기존 release를 수정하지 않고 새 커밋을
SSH로 배포했다. source 8,286개·SDK 의존 55,672개 파일, 실제 SDK import/compile
검증 후 새 고정 release와 state가 `READY`로 활성화됐다.

새 실행의 reserve는 동시 pytest 세 작업의 메모리 예산 때문에 6 CPU / 8 GiB
여유 기준에서 거절됐다. 이때도 start intent를 만들거나 서비스를 시작하지 않았다.
자원 기준을 낮추거나 다른 작업의 예산을 삭제하지 않았다. 이후 runtime 결과는
별도 검증 기록으로 남겨야 한다.

## 소프트웨어 검증

첫 회귀의 수정 전 원격 실행은 advisory lock 파싱으로 1 failed였다.
수정 후 테스트가 호스트 affinity 대신 사용하지 않는 subprocess를 mock한 문제가
드러났고, 커밋 `b9a410c018`에서 16 CPU affinity를 고정해 71 passed를 확인했다.

landing 검사에서 installer의 sudoers 문자열 연결이 credential 모양으로 오탐됐다.
커밋 `01dfa86c92`는 동일한 sudoers bytes를 인접 f-string으로 출력한다.
비밀 검사 규칙과 helper 권한은 바꾸지 않았다. 이 커밋의 원격 집중 검증은
**151 passed, skip 없음**이다. helper 27개·runtime 24개·SSH CLI 20개와
release boundary 검사 80개를 포함하며 known-failure 비교는 새 실패 0개다.
노트북 pytest는 실행하지 않았다.

원본은 외부 운영 scratch의 `native-auto-deployment-2`, `native-auto-deployment-3`,
`native-first-start-lock-red`, `native-lock-affinity-green`,
`native-installed-followup-green`에 보존한다. 주소·계정 상세·전체 inventory는
private 기록에만 남긴다.

## 범위 제한

helper 설치·SDK 검증·고정 release activation을 확인했다. 격리 서비스 실행,
startup READY, task GOAL_CONFIRMED는 이 기록에서 확인하지 않았다.
실물 구동 수용·실제 시연 수집·모델 학습은 별도이며 실제 적격 episode는 0개다.

설계: [D-786](../../adr/D-786-omx-native-simulation-ssh-deployment.md),
절차: [SSH 자동 배포](../../deployment/omx-native-simulation-ssh.md).
