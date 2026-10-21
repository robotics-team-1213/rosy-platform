# 외부 데이터 경로 구현 계획

> **For agentic workers:** `superpowers:executing-plans`로 순차 구현·원격 검증하며 마지막에 읽기 전용 검토 한 번을 수행한다.

**Goal:** 로컬 host 도구가 저장소 밖 데이터 root를 사용하고 기존 상대 구조·검증·사람 판정을 보존한다.
**Architecture:** 공통 host 경로 해석은 `tools/data_paths.py`, 소비자는 기존 writer/reader다. `ROSY_DATA_ROOT`가 없으면 기존 기본값을 유지한다. 환경변수는 절대 경로만 허용하고 명시적 CLI 출력 옵션은 계속 우선한다.
**Spec:** D-356·D-379·D-637의 store/원본 계보, 기존 data/README.md. API·장치 실행 권한은 변경하지 않는다.
**Tech Stack:** Python 표준 라이브러리와 기존 perception 의존성.

## 제약과 판단

- 현재 main `cd0bd49383`에서 시작한다. 사용자는 2026-10-21 이번 작업 공간 1개 추가를 승인했고 검증·착지 후 회수한다.
- Ruling: `rosy-data/platform/` 아래 기존 `teleop/drive/perception/calibration` 상대 구조를 유지한다 — store manifest와 catalog의 기존 결속을 보존 — 임의 분류 이동은 reader와 content identity를 깨뜨릴 수 있다.
- Ruling: 배포·운영 설정이 명시한 store·모델 경로는 환경변수로 덮지 않는다 — 장치 pointer나 승인 자료를 이동으로 바꾸지 않기 위해 — 기존 배포 CLI는 명시적 경로를 계속 요구할 수 있다.
- Ruling: 새 host helper 한 파일을 signed learning payload의 정확한 허용 경로에 포함한다 — 실제 격리 payload 회귀에서 누락으로 실패했음 — tools 전체 허용이나 과거 payload의 새 필수 파일 요구는 추가하지 않는다.
- Ruling: 과거 커밋의 archive 입력은 helper 존재 여부로 선택한다 — 최종 검토에서 과거 커밋의 pathspec 실패를 재현 — 잘못 처리하면 과거 릴리스 재구성이 막힌다.
- Ruling: 기존 session 시험은 상속된 운영 data root를 fixture에서 해제한다 — 가짜 세션이 운영 root에 기록되는 문제를 재현 — 누락하면 시험이 운영 자료를 오염시킨다.
- Ruling: 비정상 환경변수는 CLI override보다 먼저 거절하는 현재 동작을 문서화한다 — 잘못된 host 설정으로 쓰기를 시작하지 않음 — 명시적 출력만 사용하는 경우에도 env 해제/수정이 필요하다. 이 사용성 한계는 유보한다.
- env 미지정·빈값·상대 경로, symlink 이탈, 명시적 CLI override, 기존 영상·catalog·보정 조회를 검증한다.
- 플랫폼 pytest는 커밋 SHA의 공식 원격 실행만 인정한다. 로컬 실제 데이터를 시험 fixture로 사용하지 않는다.

## 작업

- [ ] 새 경로·기존 경로·경로 이탈·curation 소비자의 통합 시험을 작성하고 원격 RED를 확인한다.
- [ ] host root helper와 run_data·perception 수집/정제/영상/catalog/보정 기본 경로를 연결하고 기존 회귀를 원격으로 검증한다.
- [ ] 사용자 지정 외부 root·지원 CLI·운영 설정의 우선순위를 data README에 기록한다.
- [ ] 전체 변경을 한 번 검토하고 Important 이상은 실패 재현 시험으로 수정한다. 영향 선택을 유지해 공식 land 절차로 반영한다.
- [ ] 검증된 백업과 대조한 로컬 자료를 외부 root로 이관하고 실제 reader를 확인한다. 기존 공개 예제와 원격 활성 state의 경로는 별도 판단한다.
- [ ] 원격 사람 검토 자료는 가동 중인 서비스·협업 binding·첨부를 보존하는 지원 백업으로 다룬다. 원격 내용을 공개 Git에 넣지 않는다.
