# Pinky 자동 GitHub Release 게시

`tools/release/robot_cd.py`는 운영 PC의 승인된 고정 설치본에서 실행한다.
새 main은 입력 데이터로만 읽으며, 개인키를 GitHub runner에 보내지 않는다.
설치는 [D-553](../adr/D-553-cd-speed-parallel-build-and-test-pcs.md)의 자동
빌드·서명 경로를 지속 실행하게 한다. 로봇의 설치·주행 수용은 별도다.

## 설치 준비

1. 게시 담당자를 한 명으로 정하고 기존 예약 작업·트랜잭션·공개 rollout을 확인한다.
   같은 SHA의 공개 rollout이 있으면 다시 만들지 않는다. 기존 거래 상태가 없는
   coordinator는 다른 거래를 인수하지 않고 `existing_rollout`으로 남긴다.
2. 검토·커밋된 설치 도구와 helper를 선택한다. 설치 도구는 그 소스를
   `%LOCALAPPDATA%/Rosy/robot-cd/versions/<source SHA>`에 복사하고 파일 해시를 고정한다.
   이후 main 변경은 이 실행 코드를 자동 교체하지 않는다.
3. 저장소 밖에 private JSON 설정을 만든다. 필수 입력은 `repo`, `repo_id`,
   `state_dir`, `robots`, `canary`, `key_name`이다. `canary`는 `robots`에 포함한다.
   `state_dir`은 절대 경로이며 Windows payload 추출을 위해 64자 이하여야 한다.
   `base_source_revision`은 설치된 서명 image/payload에서 확인한 전체 commit SHA다.
   추측한 최신 main을 기준선으로 쓰면 미전달 변경을 건너뛸 수 있다.
4. 기존 SSH 경로에 별도 공개 pin 파일이 필요하면 `ssh_known_hosts`에 그 파일의
   절대 경로를 지정한다. 파일이 없거나 경로에 공백·따옴표가 있으면 거절한다.
   이 설정은 버전 조회, ABI 검사, publisher의 hostname/status 조회에 모두 적용된다.
   `StrictHostKeyChecking=yes`, `BatchMode=yes`와 기존 SSH alias 설정은 유지한다.
   선택 사항 `ssh_jump`도 같은 경로에 적용된다. pin 파일을 자동 생성·교체하지 않는다.

운영 창과 canary 조건을 확인한 뒤 선택한 checkout에서 실행한다.

```powershell
powershell.exe -NoProfile -File tools/release/install_robot_cd.ps1 -ConfigPath <private-config.json> -BaseSourceRevision <verified-full-SHA>
Get-ScheduledTask -TaskName RosyRobotCD | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName RosyRobotCD | Select-Object LastRunTime, LastTaskResult, NextRunTime
```

`trusted_root`는 설치 도구가 채운다. 작업은 현재 사용자가 로그인한 동안 기본
5분마다 실행되며 `state_dir/task-output.log`와 `audit.jsonl`을 확인한다.
현재 사용자에게 GitHub 인증, 기존 개인 서명키, 승인된 pinned SSH 접근이 필요하다.
예약 작업 존재나 exit 0만으로 Release 게시·로봇 설치 성공을 판단하지 않는다.

## 거래와 실패 확인

main 변경이면 정확한 repo/workflow/SHA의 unsigned 빌드를 시작하고 같은 main push의
CI 성공 후에만 ABI 검사·서명을 진행한다. main 이외 artifact와 ABI 불일치는
자동 채널에 올리지 않는다. Release 번호는 legacy·`payload-v2`·예약 tag·장치 버전이
공유하며 더 최신 legacy/v2 Release가 있으면 과거 후보 서명을 거절한다.

완성된 full tar와 서명된 `rollout.json`을 GitHub Release에 게시한다. `canary_ok=false`
동안 canary 이외 로봇은 대기한다. 같은 거래의 fresh canary commit 결과를 확인한
publisher만 서명된 wave를 연다. 게시 직후 canary가 자동 설치를 시작할 수 있으므로
운영 창 없이 예약 작업을 활성화하지 않는다. hold·보정·idle·정상 상태·롤백 가드는 유지한다.

`delivery_held`는 `reason`을 읽는다. frozen OS 파일·서비스는 `os-image`이며 별도
OS build/sign/publish 승인이 필요하다. 이를 payload로 바꾸거나 BUILD GO를 우회하지 않는다.
기존 거래 재개는 같은 source·tar digest·canary의 서명된 rollout 일치부터 검사한다.
`canary_ok=false`, 실패·철회 또는 장치 대기를 성공으로 기록하지 않는다.
