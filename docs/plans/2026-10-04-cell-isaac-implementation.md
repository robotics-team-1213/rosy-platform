---
module: fleet
tags: [cell, palletizing, isaac, D-450]
---

# Cell · Isaac Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 저장·컴파일·서비스 제안을 제공하는 Cell 작업 화면과 Isaac 명령 수신 만료 정지를 구현한다.

**Architecture:** Cell은 기존 Fleet 프로세스의 Console 작업 화면으로 제공한다. 문서만 같은 SQLite에 저장하고 실행 원장은 기존 ProposalStore/CellJobStore를 사용한다. 제안은 설정에 명시한 실제 service principal로 만들고 승인은 기존 named operator 절차에 남긴다. Isaac은 5.1/6.x importer를 구분하고 명령 만료·pause·reset에 바퀴 목표를 제거한다.

**Tech Stack:** FastAPI, SQLite, canonical rosy-palletizing wheel, shared web controls, Isaac Sim/ROS 2 Jazzy.

## 승인과 범위

2026-10-04 사용자 `처리해줄래?`로 구현을 승인했다. D-450/D-434에 따라 Gazebo/Isaac 실동작은 모델 PC에서 검증한다. 실물 로봇 주행·정지·E-Stop 해제는 이 구현의 검증 수단이 아니다. 기존 운영 사이트를 테스트 사이트로 바꾸지 않는다.

### Task 1: 문서 revision 저장

- Create: `operations/fleet/fleet/server/cell_app_store.py`
- Test: `operations/fleet/test/test_cell_app_store.py`
1. restart persistence, compare-and-swap conflict, invalid/nonfinite JSON과 최대 크기를 검사하는 실패 테스트를 작성한다.
2. `python -m pytest operations/fleet/test/test_cell_app_store.py -q`에서 실패를 확인한다.
3. Fleet DB의 별도 문서 테이블과 digest 비교 트랜잭션을 구현한다. 실행 테이블은 복제하지 않는다.
4. 같은 명령으로 통과를 확인한다.

### Task 2: 컴파일·제안 composition

- Create: `operations/fleet/fleet/server/cell_app_routes.py`
- Modify: `operations/fleet/fleet/server/{app,mission_routes,cell_goal_evidence}.py`
- Create: `contracts/foundation/core_common/protocol/cell_app.py`
- Modify: `contracts/foundation/core_common/protocol/schemas.py` (public re-exports)
- Modify: `docs/reference/ROSY API & Protocol Reference.md`
- Test: `operations/fleet/test/test_cell_app_api.py`
1. viewer/service 저장 거절, named operator 저장, stale digest 컴파일 거절, 미리보기의 실행 부작용 없음, 설정된 service 제안과 별도 승인, 같은 key 재시도 동일 ID를 실패 테스트로 고정한다.
2. 대상 pytest에서 실패를 확인한다.
3. 기존 proposal create/resolve callable을 composition으로 재사용하고 명시 service ID를 registry에서 검증한다. 토큰은 브라우저에 보내지 않는다. POST 문서 저장도 기존 API audit에 기록된다.
4. 기존 Cell Job API 회귀와 신규 테스트를 함께 실행한다. 새 wire 계약과 API 문서는 같은 변경에 둔다.

### Task 3: Console 안의 Cell 작업 화면

- Create: `operations/fleet/fleet/server/web/{cell.html,cell.js,cell.css}`
- Modify: `operations/fleet/fleet/server/static_routes.py`, `shared/web/surfaces.yaml`
1. 인증, 문서 입력·저장·다시 읽기, canonical 미리보기, scope와 request key를 포함한 명시 제안, 기존 Console 승인 링크를 구현한다.
2. 기존 Console 프로세스/포트/CSP/allowlist를 사용한다. 별도 Cell surface와 중복 mission 소유권을 만들지 않는다.
3. 조작 실패는 표시하고 자동 재제안·승인·UNKNOWN 재실행을 하지 않는다. 문서 변경은 기존 preview를 무효화한다.
4. host TestClient 및 실제 PC 브라우저에서 저장→미리보기→제안→별도 승인 흐름을 검증한다. 브라우저 검증을 하지 못하면 NOT_RUN으로 기록한다.

### Task 4: Isaac importer와 watchdog

- Modify: `learning/envs/isaac/{run_rosy,import_omx}.py`
- Create: 해당 폴더의 capability/watchdog helper와 `test/` 테스트
1. 순수 policy 테스트의 RED를 확인한다.
2. 5.1 command importer와 6.x API를 기능 검사로 구분한다. partial/broken 현대 API는 fallback하지 않는다.
3. 새 Twist 수신 시각을 기준으로 만료시키고 실행 루프에서 pause/reset/stale graph의 USD wheel target까지 zero한다. 최종 ROS command publisher는 추가하지 않는다.
4. 정책 테스트와 runner integration 검사를 실행한다. SDK 실동작은 모델 PC에서 별도로 판단한다.

### Task 5: 통합과 실제 검증

1. 모델 PC identity/GPU/ROS/Gazebo/Isaac 버전과 기존 clock/writer를 읽기 전용으로 확인한다.
2. 별도 scratch/install을 사용해 기존 원격 dirty checkout을 보존한다. Gazebo와 Isaac을 동시에 같은 robot clock/writer로 실행하지 않는다.
3. G1 앱 검증, I0 설치 baseline, I1 driving/expiry stop을 각각 증거로 기록한다. I2–I4 및 original C6 sheet 전송은 실제 통과 전까지 미완료다.
4. 독립 spec review 후 quality review를 받는다. affected tests, harness generate/lint, pre-push gate를 통과시킨다.
5. 구현 commit과 PR CI를 확인하고 승인된 통합 범위만 merge한다. SOURCE/LOCAL/ROS-SIM/ARTIFACT/DEVICE/FIELD 결과를 구분한다.
