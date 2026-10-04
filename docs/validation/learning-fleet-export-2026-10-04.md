# 학습 Episode와 Fleet receipt 오프라인 연결 검증

2026-10-04. 기준 HEAD `7a6c5b6500b0db7532f104e3bb6a8b792f3950cd` 이후
`learning/registry/policy/fleet_join.py` 변경. [계획](../plans/2026-10-04-learning-fleet-export.md).

## SOURCE / HOST

기존 D-18 DeviceActionReceipt schema를 재사용했다. 단일 action/attempt가 모두 일치하고
Episode.device와 receipt.instance_id가 일치해야 binding을 만든다. 여러 키 목록의
조합을 추정하지 않는다. missing/ambiguous/mismatch/terminal conflict는 unmatched로
보존한다. task/judge/policy unknown과 receipt Action 상태는 분리한다.
원본 Episode 파일 SHA/bytes와 입력 manifest/receipt hash를 검증하고 기존 export
덮어쓰기를 거절한다. 원본 metadata/정책 원장/운영 설정은 바꾸지 않는다.

TDD RED: 새 모듈이 없어 ModuleNotFoundError 확인.
호스트 targeted12passed, registry 및 공통 artifact 회귀68passed.
별도 read-only 리뷰의 독립 targeted12passed, blocking finding 없음.
실행은 Windows Python3.14이며 ROS/장치 접속·명령은 없었다.

문서/배치 관련 gate98passed/1skipped/26warnings. skipped는 Windows에서
bash folder smoke를 실행하지 않는 기존 조건이며 26warnings는 기존 last_verified
이력 경고다. D-427 parts boundary18passed. exporter source SHA-256:
`d3213121cf15c030aec9c23c7cfb01a9fc4c72a360bfe3d3b81e8e780f3cb047`.

## 실제 데이터 재독출

`X:/DevTemp/rosy-learning-audit-20261004/policy-registry/datasets/`의 5개
Dataset snapshot에 closure를 실행했다. 선언 파일 membership/hash, 공통 Episode와
OMX/Pinky profile body 검증을 통과했다. 총 Episode10개(OMX6/Pinky4)는 모두
action_ids/attempt_ids가 비어 있고 policy revision도 null이다.
`fleet-join-readiness-audit.json`에 원본 revision·profile·환경·correlations·outcome과
exporter source SHA를 기록했다. 이 감사는 당시 source snapshot 상태에 대한 증거다.

따라서 join-ready=0이며 실제 receipt join은 **미실행**이다. 합성 테스트 receipt를
실제 데이터에 붙이지 않았다. 키 없는 시연에서 Fleet mission/step이나 정책 실행을
추정하지 않는다. 제외된 Pinky session도 profile closure 감사에 포함되었으나
그 원본 scan 이상을 승인된 학습 입력으로 바꾼 것은 아니다.

## 남은 수용

실제 owner recorder/export가 action/attempt를 보존하고 독립적으로 받은 receipt를
같은 instance·실행 환경에서 검증해야 실제 연결을 확인할 수 있다. 해시는 byte
보존이며 receipt 인증·서버 수신·정책 실행·과제 성공을 증명하지 않는다.
owner 설치 trust/lease/generation/stale/HOLD·SIM 독립 과제·shadow/stop/rollback·
Fleet 수신 원장 readback·DEVICE/FIELD는 미완료다. 전체 목표는 active다.
