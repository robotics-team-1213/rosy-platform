# model-watch 배치 정정 — D-434

## 계약과 이전 오류

Accepted D-434는 모델 PC가 학습·라벨·store·intake·watch·shadow 전달을 맡고
관제 PC에는 사이트 스택만 두도록 정한다. learning-pipeline-closure 계획 M1.5도
설치 대상을 모델 PC로 명시한다. 앞서 관제에 준비한 system model-watch 설치 후보는
이 계약과 충돌했다. 사용자의 관리자 실행 방식 선택을 배치 변경 결정으로 해석하지 않는다.

실제 system 설치 전에 발견했다. 관제의 user-home intake/accepted/rejected 결과는
과거 별도 재현 증거로 보존하며 운영 배치로 인정하지 않는다. 이전 관제 설치 요청은
철회했다. 관제 installer 원본과 SHA를 별도 보존하고 실행 경로는 exit2로 중단시켰다.
기존 사이트 서비스·데이터·등록·개인 키는 삭제하거나 변경하지 않았다.

## 모델 PC 준비

- 현재 모델 PC model-watch service/timer는 not-found이며 system source/venv/store/config도
  아직 없다. 모델 PC의 기존 user store는 그대로 보존한다.
- 첫 온라인 의존성 준비는 PyPI 접속 시간 초과로 종료됐다. pid/단계/실패 결과를 보존하고
  terminal 상태를 확인한 뒤 별도 오프라인 준비로 진행했다.
- Windows에서 Python3.12 Linux용 wheel10개를 수집하고 metadata 버전과 파일 SHA를
  고정했다. archive 전송이 끝난 뒤 원격 archive SHA와 wheel10개 SHA를 대조했다.
  네트워크가 필요 없는 별도 venv에서 sync/check, CPU runtime imports, 실제 JSONL
  생성/fsync와 기존 installer dry-run이 모두 exit0이었다. GPU 학습 venv는 변경하지 않았다.
- source archive SHA는 이전 Linux204pass 후보와 같은
  c38b83cc42390aec9c8d19f2c7afd8014acded711cf801a1257f7e922ae31302이다.
  dependency archive SHA는
  0a1b368a54ef81c86ca443a0bb7861e7497d06253eccdc08434ea042c7a2c190이다.
  lock SHA는 4fb25356ce48a39c46d65668000f201e781051f46c029e130819da5e91977a20이다.
- Python base는 /usr/bin/python3.12다. ProtectHome와 충돌하는 홈 내부 interpreter를
  서비스에 사용하지 않는다. StateDirectory journal 보강은 그대로 적용된다.
- 모델 PC용 관리자 script는 pinned source/dependencies/tool을 확인하고 기존 system
  경로가 있으면 중단한다. placeholder 설정으로 timer는 비활성 상태다.
  관리자 sudo 실행과 실제 systemd 계정/sandbox 검증은 아직 미실행이다.

관리자 후보의 독립 검토에서 tool 재읽기 교체와 기존 unit/timer 상태 guard 누락을
발견해 수정했다. tool은 다시 검증한 동일 bytes를 root 소유 exclusive snapshot에
저장·fsync하고 그 복사본만 실행한다. 기존 경로·dangling symlink·unit/timer의
load/active/enablement 상태는 쓰기 전에 거절한다. 비특권 UID1000의 native shim
시험에서 loaded/masked/active/enabled 네 경우 모두 exit1, 변경 명령0을 확인했다.
관제의 철회 script는 실제 exit2, 모델 후보의 bash syntax는 exit0이었다.
독립 재검토는 blocking issue 없이 승인했다. 후보 SHA는
9052929a5bb7b8ed580e440067c0201a53940344c9664827726bf83547858f31이다.

private 요청서·명령·계정·실행 결과는
X:/DevTemp/rosy-learning-audit-20261004/model-watch-placement-v1와 model-admin-request.md다.
관제 요청서는 철회 상태다. 외부 메시지는 보내지 않았다.

## 남은 실행 경계

모델 PC system 설치 후 canonical store/eval/champion history와 replay를 연결해야 한다.
전용 model-host robot key/host pin, 실제 연결·HOLD·doctor, shadow loader와 rollback,
사람 라벨·새 홀드아웃, 정책 trust·owner/Fleet 결과와 DEVICE/FIELD 증거가 남는다.
운영 주행 활성화, HOLD 해제와 물리 명령은 실행하지 않았다. 전체 목표는 미완료다.
