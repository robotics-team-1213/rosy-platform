# 비공개 운영 저장소와 staging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비공개 `rosy-ops`에 staging 설정·운영 안내·설정 검사 CI를 마련한다.

**Architecture:** 제품 코드는 공개 저장소 한 곳에서 관리한다. 비공개 저장소는 고정 소스 SHA와 산출물·설정·검증 기록을 연결한다. 첫 설정은 `HOLD`이며 CI는 구성만 검사하고 호스트에 접속하거나 배포하지 않는다.

**Tech Stack:** GitHub private repository, Python 3.12, PyYAML, GitHub Actions.

**Spec:** [D-784](../adr/D-784-public-source-private-ops-staging.md)

## Global Constraints

- Fleet·웹·시뮬레이션만 초기 범위에 둔다. 실제 로봇·운영 DB·운영 자격증명을 연결하지 않는다.
- GitHub Free 비공개 Environments의 승인 기능을 가정하지 않는다. CI에는 읽기 전용 `contents: read`만 부여한다.
- 토큰·비밀번호·개인키·원본 자료를 Git에 넣지 않는다. 제품 코드·릴리스 서명키를 복제하지 않는다.
- 이 계획은 설정·검증 CI 준비까지다. 대상 호스트·담당자·접속 범위·격리 근거가 정해진 뒤 실제 실행 환경을 별도 구성한다.
- 사용자 지시에 따라 원격 시험 PC 접속은 생략하고 정적 검사와 GitHub CI로 검증한다. 미실행 원격·장치 검사를 기록한다.

## Review Focus

- 빈 초기 설정은 `HOLD`여야 하며 준비 완료로 표시되지 않아야 한다.
- `main`·`latest`·잘못된 SHA/digest는 준비 완료 검사에서 거절해야 한다.
- 필수 설정 누락·알 수 없는 필드·비밀값 필드는 구성 검사에서 거절해야 한다.
- 준비 완료라도 호스트 격리나 실제 시험을 실행했다고 표시하지 않아야 한다.
- 공개 소스 PR이나 private CI가 장치·운영망·배포 자격증명을 사용하지 않아야 한다.

## Task 1: 운영 설정과 검사

**Files (private repo):** `README.md`, `AGENTS.md`, `.gitignore`, `environments/staging/desired.yaml`, `docs/staging.md`, `tools/check_staging.py`, `tests/test_check_staging.py`, `requirements.txt`, `.github/workflows/check.yml`.

**Interfaces:** `check_config(config: dict, require_ready: bool = False) -> list[str]`. `python tools/check_staging.py [--require-ready]`는 고정 staging 경로를 읽고 오류가 있으면 exit 1, 없으면 exit 0이다. 일반 검사는 명시적 `HOLD`를 허용하며 준비 완료 검사는 `READY`와 모든 필수 근거를 요구한다. 어느 모드도 배포하지 않는다.

- [ ] 로컬 준비 위치는 제품 저장소와 분리한 `C:/Dev/Robot/rosy-ops`를 사용한다. 초기 README·AGENTS와 CI·시험 초안을 독립 검토한 뒤 조직에 private 저장소를 생성한다. main에는 안내부터 게시하고 기능 branch의 Draft PR에서 아래 실패→성공 검증을 진행한다. 기존 경로·저장소가 있으면 먼저 확인하며 덮어쓰지 않는다.
- [ ] 설정 형식을 정한다: `schema_version: 1`, `environment: staging`, `state: HOLD|READY`; `source: {repository, commit}`; `artifact: {reference, sha256}`; `target: {host, owner, access_scope, isolation_receipt}`; `previous_release`, `validation_receipt`. 초기값은 공개 저장소 이름과 HOLD 외에 null로 둔다.
- [ ] `tests/test_check_staging.py`에 HOLD 일반 검사 통과/준비 검사 실패, 모든 근거가 있는 합성 READY 통과, 필수 필드 누락·알 수 없는 필드·비밀 필드·가변 ref·잘못된 hash·누락된 target/receipt 거절을 고정한다. GitHub CI에서 구현 전 실패를 확인한다.
- [ ] `check_config`를 구현한다. source commit은 40자리 hex, artifact sha256은 64자리 hex, artifact reference는 digest 고정 OCI 참조 또는 가변 별칭이 없는 HTTPS 산출물 URL만 허용한다. target/rollback/receipt는 준비 완료 모드에서 빈 값과 예시 placeholder를 거절한다. 이전 배포가 없는 첫 실행은 `previous_release: bootstrap`을 명시하고 staging 폐기·재생성 절차를 문서화한다.
- [ ] CI는 GitHub-hosted runner에서 unittest와 일반 구성 검사만 실행한다. 환경·저장소 secret, SSH, self-hosted runner, 외부 repo checkout, 배포 명령을 사용하지 않는다. 설정 값을 로그에 출력하지 않고 경로별 오류만 남긴다.
- [ ] README에는 작업 순서·자료 구분·현재 HOLD와 한 개 그림, AGENTS에는 위 권한 범위와 검사 명령, staging 안내에는 채울 근거·수동 검증·실패 시 복구 순서를 적는다. 제품 코드의 D-784와 배포 계약을 연결한다.

## Task 2: 비공개 게시와 검토

- [ ] 로컬 초기 변경을 독립 검토하고 발견 사항을 고친다. 기존 저장소가 생겼으면 먼저 확인하며 덮어쓰지 않는다.
- [ ] 기능 branch/PR에서 설정과 CI를 검증한다. 최신 head의 개별 잡 성공과 private 상태를 확인하고 같은 SHA를 병합한다.
- [ ] 이슈·위키·병합 방식 등은 필요한 범위만 설정한다. 새 유료 기능이나 저장소·환경 secret은 만들지 않는다. 실제 접근 강제 규칙이 지원되지 않으면 문서상 규칙과 구분해 기록한다.

## Task 3: 공개 문서 연결

- [ ] 공개 팀 가이드에 코드·내부 운영 설정·비밀·자료의 보관 경계를 반영하고 실제 값은 쓰지 않는다. 생성 기록을 갱신한다.
- [ ] 원격 시험 생략 지시를 PR에 기록하고, 정적 검사·독립 검토·GitHub CI로 공개 문서 변경을 검증해 게시·병합한다. staging 호스트 기동·로봇·DEVICE/FIELD는 미실행으로 기록한다.

**완료 조건:** private 저장소와 검증 CI, 명시적 HOLD 설정, 운영 안내, 공개 문서 연결이 있고 실제 GitHub 결과를 확인했다. 실행 환경의 완료 조건은 D-784의 격리·기능·복구 검증으로 별도 판정한다.
