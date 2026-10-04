# Owner policy installation binding implementation plan

**Goal:** owner 실행 전 고정 설치 binding과 실제 PolicyArtifact bytes를 대조한다.
**Architecture:** middleware/execution/local은 learning registry를 조회하지 않고 contracts/learning의 stdlib validator만 사용한다. 설치 profile의 pinned policy revision·장치/카메라·controller/envelope·정규화·행동 envelope·stale budget을 검사한다. 승인/lease/fence는 별도 실행 계약이며 이 loader는 명령을 보내지 않는다.
**Tech Stack:** Python dataclass, canonical JSON, ROS/torch-free artifact wheel.

1. middleware/execution/local/test/test_policy_install.py에 고정 binding 불일치,
   설치 limits/timing보다 넓은 정책 거절, load 후 file 변조/reseal/설치 scope 변경
   거절 테스트를 작성하고 RED를 확인한다.
2. src/rosy/execution/local/policy_install.py와 wheel dependency를 추가한다.
   metadata bytes를 불변 보존하고 owner 소비 직전에 recheck할 수 있게 한다.
3. 실제 OMX/Pinky3개 연구 artifact를 검사한다. 설치 binding이 제공되지 않았다면
   연구 manifest의 값으로 승인 profile을 만들지 않는다. 장치 활성화는 없다.
4. 관련 회귀·D-427 boundary·독립 리뷰, 문서와 점검 보고서를 보강한다.

## 조사에서 확인된 실행 경계

현재 worktree와 갱신한 origin/main 모두 구체 D-442 wire 파일이 없다.
Fleet ActionGrant는 PICK_PLACE/CELL_TRANSFER이며 범용 policy lease로 해석할 수 없다.
D-390 seat는 sim-only Pilot 권한이고 정책 승격을 대신하지 않는다.
CORE nav slot과 ArmCommandOwner owner 문자열만으로 정책 dispatch를 허가하지 않는다.
후속은 승인된 local envelope Skill/정책 lease를 기존 owner와 StopFence에 연결하고
generation/stale/HOLD/stop/rollback을 실제 SIM에서 판정하는 것이다. 이 loader의
성공을 승격/활성화/실행/독립 과제 성공으로 표시하지 않는다.
