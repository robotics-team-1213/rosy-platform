# 관제 AI 게시 실행 계획

**Goal:** 검증한 관제 AI와 D-831을 공개 원격 구조에 분리 적용하고 같은 SHA의 검증·PR·CI를 거쳐 게시한다.

**Architecture:** 원격의 `operations/site_ui/console`·기존 정적 allowlist·기존 Task owner를 유지한다. 공통 계약을 먼저 게시하고 후속 기능은 그 계약을 사용한다. 기존 보호 설치와 CORE 최종 명령 권한을 보존한다.

**Tech Stack:** Python, Pydantic, Fleet/FastAPI, Console ES modules, 기존 원격 pytest·GitHub CI.

**Spec:** D-810·D-821·D-831 및 기존 `2026-10-21-operator-ai-field-acceptance.md`. 원본 구현의 source commit은 로컬 `e83e3298293a4ecfaf5185ee7c05b94f7ab4302e`이며 여기서 검증돼 있다. 원본 SHA의 모델 receipt를 새 게시 SHA에 재사용하지 않는다.

## 제약과 검토점

- 사용자가 이번 게시용 작업공간 1개 임시 추가를 허용했다. 동료 작업과 main의 `aff1.log`는 보존한다.
- 공유 계약 변경은 기능과 별도 게시한다. 원격 API v1.293과 기존 변경을 보존하며 예약한 v1.294로 추가한다.
- 모델·대화 답변은 실행 승인이 아니다. 새 Discord profile은 제안 전용을 유지한다.
- 현재 panel의 미게시 `app-runtime.js` 의존성을 복사하지 않는다. 원격 정적 자산·설치 wheel/sdist와 브라우저를 검증한다.
- 신원 위조·부정문·유한 수치·동일 요청 멱등성·권한 철회·기존 Discord 경로를 확인한다.
- 소스 변경은 커밋한 SHA로 원격 시험한다. selector의 FULL을 축소하지 않는다.
- 원격의 과대 Fleet/Console에 행을 더할 수 없어 assistant 소스는 기존 `server/work` holder에 두고 기존 Python 신원을 명시적으로 패키징한다. Console은 기존 D-798 auth/goal/refresh 팩토리를 shared holder로 분리한다. 동작·공개 자산 URL은 유지하고 size ceiling은 낮춘다.

## 1. 공유 계약 게시

- [x] foundation 경계 시험으로 원격에 없는 assistant DTO를 재현한다.
- [x] `protocol/assistant.py`, D-810/D-821, ADR Log, API 계약과 고정 버전을 반영한다.
- [ ] 관련 원격 시험·필수 검사·독립 검토·pre-push·PR 최신 SHA CI를 확인하고 병합한다.

## 2. 관제 AI와 전처리 게시

- [x] 원격 기준에서 Fleet assistant·기존 UI 연결·broker·보호 설치·ko/en·명시적 좌표 인계를 적용한다.
- [x] D-831 공통 전처리·해석 검증·계측·source closure·새 Discord 실행 OFF를 적용한다.
- [ ] 원격 전체 선택·설치 산출물·브라우저·고정 모델 Console/Discord를 검증한다.
- [ ] 독립 검토한 최신 head를 PR로 게시하고 모든 개별 CI 결과를 확인해 병합한다.

## 3. 운영 연결과 정리

- [ ] 최종 배포 SHA에서 독립 평가·검토한 snapshot·설정 hash·서명 후보를 준비한다.
- [ ] 관리자 실행 환경이 있을 때만 보호 설치 check·설치·readback과 조회 전용 배포를 수행한다.
- [ ] 실제 발화·기명 Discord 왕복·장치 수용은 현장 실행표에 실제 관측을 기록한다.
- [ ] 결과와 미실행 조건을 기록하고 임시 작업공간을 공식 도구로 정리한다.
