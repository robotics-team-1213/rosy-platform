# 학습 산출물 계약과 OMX 공통 Episode 변환 검증

2026-10-04 KST. D-449 Proposed 초안과 공용 contracts/learning wheel을 구현했다.
기존 행동 실행 owner나 safety 코드를 바꾸지 않았다. 전체 목표의 M3 시작 증거이며
정책 학습·SIM 실행·장치/현장 수용을 완료한 기록이 아니다.

## 구현

stdlib-only `rosy.contracts.learning`에 Episode/DatasetManifest/PolicyArtifact/
PromotionRecord canonical revision·파일 해시·단위/순서/owner·단계 증거 검사를 추가했다.
root 없는 검증은 구조만, root 있는 검증은 실제 bytes·SHA까지 확인한다.
검증된 metadata가 보고서 진위나 실행 권한을 보증하지는 않는다.

`common_episode.py <original-omx-episode> <new-output>`는 기존 validated OMX 원본의
manifest/samples/events/이미지를 그대로 보존한다. policy/camera_profile과 Action
결과는 확인되지 않은 상태로 유지한다. operator 과제 표시는 operator 근거로만
기록하며 sim ground truth나 독립 판정으로 승격하지 않는다. 동일 capture/state 시계와
별도 received wall 필드·rad action을 보존한다. 원본 변조와 재출력 덮어쓰기는 거절한다.

아직 기존 middleware validator import에 의존하므로 D-427 Q6 frozen edge를 없앴다고
주장하지 않는다. wave 2b의 validator 이동·Pinky/Pilot 변환과 Fleet join은 남아 있다.

## 시험과 산출물

- 신규 공통 계약: 16 passed. revision 변조, 실제 파일 bytes/SHA, 시계/경로,
  device 상관 키, policy owner/joint order/단위/stale/reset, dataset 중복,
  unknown 평가·잘못된 policy revision·stage 도약 거절을 확인했다.
- OMX 변환+기존 export+공통 계약: 22 passed/1 skipped(호스트 LeRobot 없음).
  실제 DemonstrationRecorder 테스트 fixture의 2프레임 원본을 변환/재독출했다.
  합성 fixture이며 실제 Gazebo run·사람 과제 판정·정책 추론 증거가 아니다.
- 소유/import 방향·문서 배치·폴더·harness 계약: 108 passed/1 skipped,
  기존 26 warnings. 새 코드도 tracked 상태에서 소유 검사를 실행했다.
- wheel 빌드는 X 드라이브 복사본에서 실행했다. 산출물
  `X:/DevTemp/learning-contract-wheel-20261004/wheels/rosy_contracts_learning-0.1.0-py3-none-any.whl`,
  SHA `8ab5c517ea76d6326bf961a7a259ee2df10397652cfdb8812559528ae554422d`.
- 변환 fixture와 상태는 `X:/DevTemp/common-episode-green-20261004/`에 보존했다.
- 최종 소유/import·파일 예산/모듈 구조 검사 51 passed. wheel을 X의 별도 target에
  설치하고 Python isolated 모드로 import했다. runtime dependencies 없음과 torch
  미로드를 확인했다. harness generate 완료, lint 0 errors/기존 26 warnings.
- 실행 소스 SHA: artifacts.py
  `3eb8dfcb3a4bd44934ff8327fde6045d5f175b83399b12c8536dfa2a66c4d5a9`,
  common_episode.py
  `bc7dbcbe97dae9823b3a62e0ef37b05fb99ad2030ff0fa06a9dccac5a2532775`.

## 잔여 gate

승격 원장·보고서 독립 검증/승인 진위, install binding loader·owner candidate admission,
lease/generation/stale/HOLD/stop/reset enforcement, OMX 학습→offline/SIM 평가,
Pinky 주행 정책→Fleet mission/action/policy 결과 join과 Isaac 실행은 미완료다.
모델 PC의 Tailscale 추가 인증은 대기 중이며 대기 중인 동일 SSH handle을 조회했다.
기존 operator hold 해제·shadow overwrite·물리 motion·운영 활성화는 수행하지 않았다.
목표는 active다.
