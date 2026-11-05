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

`delivery_held`는 `reason`을 읽는다. frozen OS 파일·서비스는 `os-image`이며 아래
engineering 게시 opt-in이 없으면 대기한다. 이를 payload로 바꾸거나 BUILD GO를 우회하지 않는다.
기존 거래 재개는 같은 source·tar digest·canary의 서명된 rollout 일치부터 검사한다.
`canary_ok=false`, 실패·철회 또는 장치 대기를 성공으로 기록하지 않는다.

## OS engineering 게시

OS 게시를 승인한 운영자는 private JSON에 `os_engineering: true`와
`os_cms_private_key`를 추가한다. 후자는 기존 운영 PC의 CMS 개인키 **절대 경로**이며
키나 private JSON을 저장소·GitHub runner에 복사하지 않는다. Ed25519 키는 기존
`key_name`을 사용한다. CMS 공개 SPKI·인증서·빌드 pin 검증도 그대로 적용한다.
`source_repository`는 private JSON에서 수명이 긴 정본 Git 저장소의 절대 경로로 지정한다.
설치 도구는 지정한 값을 보존하고, 속성이 없을 때만 설치에 사용한 저장소 경로를 기본값으로
기록한다. worktree에서 설치했다면 정리 전에 이 경로가 곧 삭제할 worktree를 가리키지
않는지 확인한다. 고정 설치본은 남더라도 Git archive의 데이터원이 사라지면 준비가 중단된다.
지정한 저장소에서도 정확한 tools commit object와 설치 파일의 byte 대조는 그대로 요구하며,
경로를 바꾸어 최신 HEAD 코드로 대체하거나 검증을 건너뛰지 않는다.

최초 활성화 전에 공개 main에 필요한 OS 수정이 포함됐는지 전체 SHA와 ancestry로
확인한다. 작업은 설치 1분 뒤 실행될 수 있으므로, 옛 main을 빌드할 상태에서 먼저
활성화하지 않는다. 이미 빌드 중인 같은 source의 작업·예약 tag·상태 파일도 확인한다.

하나의 coordinator와 잠금·`state.json`을 그대로 쓴다. 정확한 main push CI 성공과
main ancestry를 확인하고, `payload-reserved-<id>`를 원자 예약하여 그 tag에서만 이미지
workflow를 dispatch한다. workflow·repo/head repo ID·source SHA·tag·run ID·run attempt를
고정하고, 완료된 같은 run의 source-bound artifact ID·크기·SHA256까지 검증한다.
공개 tag `os-pinky-pro-<id>`는 빌드 예약 tag와 구분한다. 긴 CI 빌드는 tick마다
관측하며 기다리는 동안 작업 프로세스를 유지하지 않는다.

서명 PC는 들어오는 main의 코드를 실행하지 않는다. 설치 manifest의 **tools SHA**와
설치 파일 해시·그 SHA의 Git blob을 대조하고, 정확한 tools SHA의 `git archive`만
소유 VM에 전달한다. 이미지의 candidate SHA는 별도로 검사한다. 로컬 CMS 키는
기존 외부 서명 절차에만 사용하고 VM에도 전달하지 않는다. 독립적인 이미지·factory
인증, CMS/verity 및 최종 consumer 검증을 거쳐 완성된 다섯 자산만 노출한다.

자동 OS 게시는 항상 **`canary=[]`, `canary_ok=false`**를 서명한다. 이 정책은 모든
현재·미래 기체의 `authorize`를 DEFER한다. prerelease 표시나 `canary_ok=false`만으로는
닫힌 배포가 되지 않는다. 목록에 실제 기체가 있으면 그 기체는 즉시 허용되기 때문이다.
자동 route는 실제 OS canary 활성화나 승격을 수행하지 않는다.

게시 전에 nonce·source·tag·각 transport 자산의 크기/해시를 원장에 저장한다. 같은 nonce와
숫자 Release ID의 소유 초안만 재개하며, 맞는 기존 자산은 보존하고 빠진 자산만 올린다.
불명 초안·다른 source·다른 자산은 덮지 않는다. 공개 후에는 다시 GET하여 public
prerelease·정확한 tag SHA·전체 자산 크기/해시와 실제 서명 sidecar 바이트를 검증한다.
그 증거가 있어야 `os_published`를 남긴다. `deployed_sha`와 `delivery_base_sha`는 진전시키지
않으므로 게시를 기체 설치로 기록하지 않는다.

재시작은 같은 run/attempt와 같은 초안을 관측한다. dispatch 등록이 모호하거나 예약 ref의
생성 응답이 유실되면 새 빌드를 만들지 않고 검토를 요구한다. 서명 준비의 중단 자료는
소유 attempt에 보존하고 최대 세 번 준비하며, 원자적으로 완성된 signed 출력은 재검증해
재사용한다. 자동 준비의 다운로드는 1시간, 네 guest 작업은 각각 1시간, 기존 검증된
guest 전송은 8시간 상한이다. OS opt-in 설치의 예약 작업 한도는 이를 감안해 16시간이며
payload 전용 설치는 기존 60분이다. 공개 도구 캐시 준비 실패도 성공으로 처리하지 않는다.

이 경로는 engineering GitHub Release 게시다. production `BUILD_GO`, 장치의 idle/정지·
claim·source health·trial/rollback 가드를 바꾸지 않는다. 실제 OS 설치·재부팅·새 G4·SLAM
수용은 별도다. 기존 unit 문제와 frozen OS 소유 경계는
[검증된 OS poll 교훈](../solutions/deployment/os-update-poll-starts-conflicting-io-2026-11-05.md)을 따른다.

검증 기록(2026-11-06): source commit `541621bd8a47a1752a1e4efb565d0696bec8cf02`를 원격 시험 PC에서
OS coordinator·기존 payload coordinator·publisher·preparer·고정 snapshot·완전 source inventory·
rollout·영향 분류의 8개 시험 파일로 확인했다. **219 passed, skip 0, NEW/known/flaky 0**.
고정 설치본의 import 폐쇄성, run/attempt 고정, artifact 오류 거절, 실제 coordinator의 OS
분기/no-SSH, 빈 rollout의 실제 authorize 거절, 소유 초안 재개 및 공개 sidecar readback을
포함한다. VM·RAUC 동작은 해당 기존 시험의 모델/도구 fixture 범위이며, 이 결과가 실제
GitHub 이미지 빌드·운영 키 서명·공개 게시·Windows 예약 작업·기체 설치를 실행했다는 뜻은 아니다.
최초 운영 실행에서는 그 단계별 원장과 실제 GitHub 자산을 별도로 확인해야 한다.
