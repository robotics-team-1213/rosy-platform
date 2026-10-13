# ROSY 운영 UI 역할·토큰 통일 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 등록된 ROSY 표면마다 목적과 정보 위계를 구현하고, 시각 값은 공용 토큰에서 읽으며, 조작·접근성·반응형 회귀와 설치본 확인까지 마감한다.

**Architecture:** `shared/web/surfaces.yaml`을 표면 목록의 단일 출처로 사용한다. `tokens.css` → 공용 부품 → 화면 배치 순서로 고치며 기존 조회·명령 소유자를 유지한다. 원시 값 예외와 native/LCD 사본은 출처를 추적하고, 같은 값의 수동 복제를 줄이며 계약 검사로 재발을 막는다.

**Tech Stack:** 기존 CSS 토큰, Web Components, ES modules, YAML 표면 레지스트리, Android/LCD 기존 자산, 원격 pytest·Chromium. 신규 UI 프레임워크와 메시지 broker를 추가하지 않는다.

---

## 고정 기준과 범위

근거는 `DESIGN.md`, D-639·D-624·D-629·D-632·D-359 및 각 모듈의 현재 AGENTS.md다. `2026-10-11-fleet-control-layout.md`의 관제 와이어프레임은 유지한다. 등록 표면을 누락하지 않고 활성·고정 매체·PARKED 상태를 구분한다. PARKED 표면의 스타일 정리는 운용 활성화를 뜻하지 않는다.

| 표면 | 먼저 보여줄 것 | 다음 조작과 근거 | 소유자 |
|---|---|---|---|
| Fleet 관제 | 왼쪽 2/3 지도, 오른쪽 1/3 현재 개입·로봇 상태 | 알림 / 기록·근거 / 운영 도구, 현재 개입은 탭 밖 | Fleet |
| Fleet 설치·보정 | 단계·현재 대상·전제와 결과 | 해당 단계 입력·저장·승인, 관제 복귀 | Fleet 설치 문서 |
| Fleet 현장 지도 | 현재 지도·관측·보정 상태 | 지도 변경 준비와 검토, 활성 지도·초안 구분 | Fleet 지도 문서 |
| Fleet Cell | 작업 문서·준비 상태 | 편집 → 컴파일 → 제안과 수신 결과 | Cell/Fleet 기존 경로 |
| Robot | 선택 로봇의 현재 상태·지도·작업 | 운용 / 설정 / 설치·정비 목적별 내용, CORE 근거 | CORE |
| Pilot | 현재 영상·접속·조종 자격 | 운전 입력과 정지, 영상·입력 신선도 | CORE/Pilot |
| Pinky review | 검토할 영상·현재 판단 | 수정 도구·저장·다음 항목, 결과와 출처 | 학습 검토 앱 |
| Game board | 경기 상태·보드 | 경기 조작과 진행 결과 | Games |
| Control diagnostic | 진단 대상·측정·오류 | 진단 근거; PARKED 유지 | 기존 진단 앱 |
| Lane live view | 실험 영상·측정 | 실험 근거; 운용 관제와 구분 | 시뮬레이션 |
| Robot face / Pilot shell / Cam | 매체별 현재 상태와 연결 | 기존 매체 역할의 조작·표시, 공용 의미·팔레트 일치 | 각 native/LCD 소유자 |
| Web common | 공용 부품 견본과 상태 변형 | 정상 / 비활성·이유 / 실패 / 포커스 / 긴 문구 | Shared web |

시각 하드코딩은 색상·서체·글자 크기/굵기·줄 간격·자간·조작 크기·내부 여백·묶음 간격·모서리·표준 포커스 값의 수동 선언을 뜻한다. 원시 색과 척도는 공용 토큰 원본에만 둔다. 0, 1px 경계선, 비율·지도/영상 기하·도메인 수치 및 등록된 미디어 경계는 시각 척도와 구분한다. 예외 이름을 늘려 기존 실패를 숨기지 않는다.

모든 일반 조작과 비상정지는 최소 48px·라벨 14px·좌우 12px를 따른다. 위험은 채움·아이콘·보이는 동사로 구분한다. 긴 문구와 거절 이유는 줄바꿈하고, 지도·영상·조작 영역의 공간을 침범하지 않는다. native/LCD는 매체의 단위와 물리 표시 한계를 유지하며 공용 의미·팔레트 출처를 따른다.

## Task 1: 현재 구조와 실패 목록 고정

**Files:** `shared/web/surfaces.yaml`, `shared/web/test/surface_registry.py`, 각 표면의 CSS/JS/HTML/native 자산, `test/browser_scope.py`.

1. 레지스트리의 모든 표면·문서·공용 소비자를 현재 Git 경로로 목록화한다.
2. 파일·셀렉터·값·현재 역할·대체 토큰·영향 시험을 기록한다. 원시 값뿐 아니라 공용 부품 덧칠과 가짜 토큰도 찾는다.
3. 이전 실패 로그를 현재 계약과 대조한다. 확인된 기존 실패도 목표 범위의 UI이면 근본 원인과 수정 대상을 기록한다.
4. 감사 결과를 이 계획의 실행 표로 확정한 뒤 해당 파일을 고친다. 새 화면 실험을 추가하지 않는다.

## Task 2: 공용 법칙과 재발 검사

**Files:** `DESIGN.md`, `shared/web/tokens.css`, `shared/web/components.css`, `shared/web/test/test_ui_token_contracts.py`, `shared/web/test/test_surface_typography_focus_contracts.py`, `shared/web/test/test_shared_controls_browser.py`, `middleware/ui/robot/styleguide/`의 실제 견본 파일.

1. 현재 토큰을 우선 사용하고 중복 값·별칭·표면의 임의 척도를 제거한다. 새 역할이 꼭 필요하면 사용처·ADR·시험을 함께 만든다.
2. 공용 조작은 공용 컴포넌트 한 곳에서 고친다. API와 callback, 비활성·거절 이유, 포커스·키보드 동작을 유지한다.
3. 누락된 HTML/JS/native 또는 표면 예외를 기존 레지스트리 검사에 연결한다. 금지 값을 넣었을 때 검사 실패를 확인한다.
4. 실제 견본과 소비자에서 높이·서체·간격·긴 문구·두 테마를 원격 브라우저로 확인하고 커밋한다.

## Task 3: 역할별 화면 정리

**Files:** `operations/ui/console/`, `middleware/ui/robot/`, `middleware/ui/pilot/`, `learning/curation/perception/review_app_web/`, `operations/apps/games/games/web/`, 레지스트리에 있는 고정·native 표면.

1. 위 역할 표의 첫 정보·현재 상태·주 동작·복귀 경로를 기존 화면에 적용한다. 같은 의미의 상태·메시지·근거 표현은 같은 공용 부품을 쓴다.
2. 남은 하드코딩을 토큰으로 바꾸고 화면 CSS는 배치만 소유하게 한다. canvas는 기존 토큰 읽기를 사용하며 native 복제의 생성·검증 경로를 명확히 한다.
3. 요청·AI 판단·Fleet 판정·CORE 수신·실행 결과를 혼동하지 않는다. 영상 출처·시각·만료와 비어 있음/실패를 같은 상태 문법으로 표시한다.
4. 각 수정의 호출자·import/export·static route·설치 자산·fixture를 함께 갱신하고 소유 파일만 커밋한다.

## Task 4: 로그 기반 회귀 검증

**Files:** `shared/web/test/`, `operations/fleet/test/`, `middleware/ui/pilot/test/`, 관련 `test/test_*browser.py`, 학습 검토 앱의 기존 시험.

1. 수정한 소비자별 시험을 커밋된 HEAD에서 `python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<topic> -- <실제 시험 경로>`로 수행한다. 노트북에서 pytest/Chromium을 실행하지 않는다.
2. `python test/known_failures.py X:/DevTemp/<topic>/run-1.txt`로 결과를 대조한다. 새 회귀는 고치고 검사를 약화하지 않는다.
3. 1920×1080·1366×768·390×844·320×568 및 필요한 짧은 화면에서 겹침·가로 넘침·지도/영상 가림·정지 조작·키보드·상태·로그를 확인한다. 등록된 두 테마와 고정 테마를 구분한다.
4. 실패의 노드·원인·SHA와 최종 통과 로그를 연결한다. 모든 UI를 완료했다고 선언하기 전에 범위 안 기존 UI 실패도 닫는다.

## Task 5: 착지·설치본 마감

**Files:** 기존 `tools/land.py`, `tools/hooks/pre-push`, CI·서명된 사이트 릴리스 경로. 별도 배포 수단을 만들지 않는다.

1. 현재 main과 통합해 관련 시험·lint·생성 기록을 확인하고 `tools/land.py`로 fast-forward 착지한다. 동료의 변경과 경로 이동을 보존한다.
2. 정상 pre-push 검사 후 푸시하고 해당 SHA의 CI 종료 결과를 확인한다.
3. 서명된 사이트 릴리스를 배포해 설치 SHA·기능 검증·실제 콘솔 DOM/규격/영상·탭 동작을 읽어 확인한다.
4. 소스/원격 시험/CI/설치본/장치/현장 증거를 구분해 보고한다. 충전 중 로봇의 정지 래치를 해제하거나 실제 동작 명령을 보내지 않는다.

## 실행 상태

- 전체 표면 감사: 등록 11개 경로와 하위 문서 확인 완료. 세 감사 담당이 독립 검토했으며, 등록 밖 독립 HTML 표면은 확인되지 않았다.
- 확정 수정 목록: Install field 덧칠 / disclosure 행·닫힌 summary / roster 접속 안내 / Site-map·Cell heading semantics / field mismatch 색 역할 / 공용 결과 paint / 캔버스 글자 역할 / Pilot 일반 조작 / native 버튼·서체·간격 생성 소비 / registry 중복 키 및 실제 역할 / 표면 전체 토큰 참조 검사.
- 공용 규칙·소비자 수정과 최종 회귀: 공용·Fleet·장치/검토 표면의 구현을 통합했다. 공용 규칙 104개, 역할 소유권 52개, Fleet/지도/영상 브라우저 116개, Robot/Pilot 브라우저 179개가 원격 통과했다. Android Cam 413개·Pilot 105개 단위 시험과 debug APK 빌드가 통과했다. 기존 UI 실패 항목은 통합 HEAD에서 독립 재검증하며, 최신 설치본 검증 전에는 완료로 표시하지 않는다.
- 선행 Fleet 와이어프레임: main 머지·푸시 완료. 폴더 이동에 따른 ROS 경계 회귀는 `8a140aeb2`에서 원격 65개 및 pre-push 4,493개 통과, CI 16개 작업 및 서명된 관제 후보 빌드 통과. 서명된 설치 SHA와 기능 검증 종료 확인. 실제 관제 1366×768·320×568에서 비상정지/알림 48/14/12, 탭 4개 및 가로 넘침 없음 확인. 같은 화면의 AI 조회는 HTTP 200·build_commit 8a140aeb2875다. 증거: X:/DevTemp/control-632-live/installed-8a140aeb2-readback.json 및 installed-8a140aeb2-site.txt. 이번 전체 표면 변경의 설치 증거는 별도로 수집한다.
- 목표 완료는 문서 작성이나 계획 승인만으로 표시하지 않는다.
