# OMX owner receipt provenance와 Fleet export 검증

2026-10-04. 기준 `6e279edccb7ab1640b64c5a00270dd11fd0b4a9b` 이후 변경.
[계획](../plans/2026-10-04-omx-owner-receipt-provenance.md).

## SOURCE / HOST

OMX recorder 원본 sample에는 ros_goal_id가 있다. common_episode 변환기에
반복 `--owner-receipt <json>` 입력을 추가해 기존 D-18 DeviceActionReceipt
schema와 sample goal 전체 coverage를 검증하고 receipt bytes를 sources에 보존했다.
동일 Action/attempt·전체 실행 identity·journal만 단일 pair로 연결한다.
원본 recorder/owner/safety 구현은 수정하지 않았다.

contracts wheel0.1.6 profile 검증기는 동일 연결을 재검산한다. receipt 없는
legacy source에 nonempty correlations를 추가하는 우회를 거절한다. Fleet export는
모든 지원 profile의 본문 검증기를 호출하며 미지원 Pilot은 거절한다. 별도 receipt의
전체 실행 identity/journal/goal이 보존된 것과 달라지면 unmatched로 남긴다.

RED7건: nonempty correlation을 근거 없이 승인하던 경우와 새 입력 부재를 재현.
독립 리뷰에서 profile 변경 및 다른 mission/generation/journal 연결 우회를 지적받아
추가 RED9건으로 재현 후 수정했다. 최종 host 관련 회귀91passed.
D-427 parts boundary18passed. 단일/다중 goal, 부분 coverage, 다른 instance/attempt/
generation/journal, 손상 source, profile 우회, 정확한 Fleet export 연결을 포함한다.
긍정 연결 테스트는 hardware-free recorder와 합성 receipt의 HOST fixture다.
실제 owner 실행·SIM/DEVICE/FIELD 결과로 표시하지 않는다.

수정 후 독립 회귀72passed/1skipped(리뷰 환경의 LeRobot 부재), 잔여 중요 문제 없음.
LeRobot0.4.4 설치 Python3.12에서 curation 전체42passed/0skipped를 실행했고
실제 LeRobot v3 write/read/video roundtrip을 포함한다. 13warnings는 기존
NumPy scalar conversion 및 torchvision video API deprecation이다.
문서/배치 gate89passed/26기존 이력 warnings, diff whitespace 검사 통과.

## ARTIFACT / 기존 데이터 호환

wheel `rosy_contracts_learning-0.1.6-py3-none-any.whl`을 X의 소스 복사에서 빌드했다.
SHA-256 `d9abd3b6093c46c1a2960e959e3b89d5440fe2275bbdef304103436e431cadf1`.
Python3.12.14의 isolated import에서 Requires-Dist 없음과 torch/PIL/numpy/yaml/
rclpy/mcap/pydantic 미로드를 확인했다. 동일 wheel로 실제 기존5Dataset/10Episode
closure와 profile body를 다시 검증했다. 원래 revision과 empty correlations를 유지한다.
증거 `X:/DevTemp/rosy-learning-audit-20261004/omx-owner-receipt-wheel-validation.json`.

소스 SHA-256:

- contracts OMX: `4aef5f36107d128ccf85ab2f2fd4f4701f9f815cbe7e29afff8f13f1f76b100b`
- common_episode: `324faaf53a986c56d1511854b4bc8a910ddc23e2fdd546ffed0c09c36989a99c`
- fleet_join: `7a989c6051db091d80b720c1bf0604fb1512bfb0db7504c2bb8cede6f14094ee`

## 남은 gate

실제 owner journal receipt 수집·인증·실행 환경 수용과 Fleet 수신 원장 readback은
미실행이다. 보존된 과제 성공은 operator 기록이고 Action 성공으로 만들어내지 않는다.
policy revision은 원본에 없으므로 null이다. 여러 Action이 섞인 녹화는 단일 pair로
축약하지 않는다. owner 정책 admission/trust/lease/generation/stale/HOLD·독립SIM
과제·shadow/stop/rollback·DEVICE/FIELD 및 전체 목표는 계속 미완료다.
