# ROSY 팀 가이드 — 무엇을 공유하고, 무엇을 작업하나

**대상:** `robotics-team-1213` org에 새로 합류한 팀원
**갱신:** 2026-10-05
**규칙 원본:** 이 문서는 안내만 한다. 계약과 규칙이 다르면 `README.md`의 「같이 하는 깃」·「핵심 계약」, SRS, ADR이 이긴다.

---

## 1. 첫날 할 일

| # | 할 일 | 끝난 기준 |
|---|---|---|
| 1 | GitHub 계정에 **2단계 인증**을 켜고 org 초대(이메일)를 수락한다 | org People에 내 아이디가 보인다 |
| 2 | git 작성자를 **내 계정**으로 설정한다 (아래) | `git log -1 --format=%ae`가 내 이메일 |
| 3 | 저장소를 클론하고 pre-push 훅을 설치한다 | `.git/hooks/pre-push`가 있다 |
| 4 | Python 3.12와 PyYAML을 준비한다. ROS 빌드·시뮬은 Ubuntu 24.04 / WSL + ROS 2 Jazzy | `python -c "import yaml"` 성공 |
| 5 | §4의 읽기 순서대로 문서를 읽는다 | 맡을 모듈의 `AGENTS.md`를 열어 봤다 |
| 6 | Notion 게스트 초대를 수락한다 | 팀 페이지가 보인다 |

```bash
git clone https://github.com/robotics-team-1213/rosy-platform.git
cd rosy-platform
git config user.name  "<내 GitHub 아이디>"
git config user.email "<내 GitHub 이메일 또는 ID+아이디@users.noreply.github.com>"
bash tools/hooks/install.sh
```

> 작성자 이메일은 **내 GitHub 계정에 등록된 것**이어야 커밋이 내 이름으로 보인다. 남의 이메일을 쓰면 커밋이 그 사람 것으로 표시된다. pre-push 훅은 알려진 잘못된 작성자를 거절한다.

---

## 2. 공유하는 것 / 공유하지 않는 것

| 무엇 | 어디서 | 누가 보나 |
|---|---|---|
| 코드, ADR, SRS, API reference, 계획·검증 문서 | GitHub `robotics-team-1213/rosy-platform` | **전 세계 공개** |
| 작업·버그 | GitHub Issues + Projects | 공개 |
| 회의록, 일정, 온보딩 메모 | Notion 팀 페이지 (게스트 초대) | 팀 |
| 현장 주소, 로봇 IP, 접속 정보 등 비공개 운영 자료 | Notion 비공개 페이지 (저장소의 gitignored `private/` 대신) | 팀 |
| Notion MCP 연동 토큰 | 메신저·Notion 비공개 페이지로 개별 전달 | 필요한 팀원 |

**저장소에 절대 올리지 않는 것** — 저장소가 공개라서 한 번 push하면 회수할 수 없다.

- 릴리스 **서명 키** — 서명은 오프라인 로컬에서만 한다 (D-437)
- 로봇 SSH 비밀번호·개인 키 — 로봇 접속은 등록 절차를 따른다 (D-418)
- 실제 로봇 IP·현장 주소·계정 — 문서에는 `<robot-ip>`처럼 쓴다 (D-226)
- API 토큰 (W&B, Notion, Bearer 등) — 스크립트는 환경변수로 읽는다

GitHub secret scanning push protection이 켜져 있어 알려진 형식의 토큰은 push 단계에서 막힌다. 형식이 없는 값은 못 막으니 직접 확인한다.

---

## 3. 일하는 방법

```
이슈 확인 → 브랜치 → 작업 → 관련 테스트 → push → PR → CI → squash 머지
```

1. **브랜치:** `main`에서 `<type>/<topic>`으로 딴다. `<type>`은 `feat` `fix` `refactor` `docs` `uiux` 중 하나, 한 브랜치에 한 주제 (D-372).
2. **계약 먼저:** 고칠 경로의 모듈 `AGENTS.md`와 관련 ADR을 연다. 외부 API·모드·프로토콜 필드는 SRS·API reference·ADR에 있는 것만 쓴다.
3. **테스트:** 바꾼 범위의 테스트를 돌리고 기존 실패와 비교한다.
   ```bash
   python tools/harness/rosy_harness.py affected --base main --run
   python -m pytest <paths> -q -rfE -p no:cacheprovider > ../run.txt
   python test/known_failures.py ../run.txt     # NEW가 있으면 내 브랜치의 실패
   ```
   전체 스위트는 GitHub CI가 돌린다. 호스트 pytest 통과는 장치·ARM64 이미지·현장 수용이 아니다.
4. **PR:** 템플릿 체크리스트를 채운다. `main`은 PR로만 들어가고 force-push·삭제는 막혀 있다. 머지는 squash 하나다.
5. **안전 경로:** `tools/harness/platform_parts.yaml`에서 `concern: safety`인 경로를 바꾸는 커밋은 메시지에 `Safety-Review: <리뷰어> <근거>` 줄이 필요하다 (D-430 §5). CI가 검사한다.
6. **ADR:** 계약·구조를 바꾸는 결정은 ADR로 남긴다. 번호는 파일을 만들기 직전에 `docs/adr`, ADR Log, `tools/harness/harness.yaml`의 `adr_gaps`를 다시 보고 고른다.
7. **실물 로봇:** 로봇은 팀이 같이 쓴다. **움직이기 전에 반드시 먼저 묻는다.** 시험은 Gazebo 시뮬레이션이 기본이다.

---

## 4. 읽기 순서

1. `README.md` — 「같이 하는 깃」, 「핵심 계약」, 「구조」
2. `CONCEPTS.md` — 도메인 용어
3. `STATUS.md` — 모듈별 게이트 상태 (SOURCE → LOCAL → ROS-SIM → ARTIFACT → DEVICE → FIELD)
4. 맡을 모듈의 `AGENTS.md`, `progress.md`
5. 필요할 때: `docs/spec/ROSY CORE SRS.md`, `docs/spec/ROSY FLEET SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, `docs/reference/ROSY ADR Log.md`

---

## 5. 무엇을 작업하나

### 5.1 작업 영역

담당은 팀 리드가 정한다. 빈 칸은 아직 담당자가 없다는 뜻이다.

| 영역 | 경로 | 주요 내용 | 장치 필요 | 담당 |
|---|---|---|---|---|
| CORE (로봇 게이트웨이) | `middleware/core/` | 외부 API, 유일한 `cmd_vel` 발행자, 서비스·이벤트 | 일부 | |
| 인지·차선 | `middleware/perception/` | 카메라·LiDAR 기반 차선/장애물 증거 | 일부 | |
| 내비게이션 | `middleware/core/navigation/` | Nav2 / SLAM | 시뮬로 가능 | |
| 장치·드라이버 | `middleware/apps/device/`, `middleware/drivers/` | Pinky Pro bringup, LED·램프·IMU·ADC, OMX | **예** | |
| Fleet (현장 관제) | `operations/fleet/` | 미션 하달, 교통정리, 콘솔 | 아니오 | |
| 현장 앱·비전 | `operations/vision/`, `operations/ui/cam/` | 천장 카메라, Rosy Cam 앱 | 일부 | |
| 화면 (웹·앱) | `middleware/ui/`, `shared/web/` | 대시보드, Pilot 앱, 공용 웹 자산 (`DESIGN.md`) | 아니오 | |
| 시뮬레이션 | `integrations/simulation/` | Gazebo 월드·다로봇 시뮬 | 아니오 | |
| 학습 | `learning/` | 데이터셋, 학습, 모델 배달 (Colab / 모델 PC) | 아니오 | |
| 배포·릴리스·CI | `deploy/`, `.github/workflows/`, `tools/` | 이미지·payload 빌드, CI | 일부 | |
| 문서·거버넌스 | `docs/` | ADR, SRS, 검증 기록 | 아니오 | |

### 5.2 처음 잡기 좋은 일

장치 없이 할 수 있고 팀 전체에 도움이 되는 것부터 고른다. 이슈로 등록한 뒤 담당을 정한다.

| 일 | 왜 필요한가 | 영역 |
|---|---|---|
| CI `ci` 워크플로 실패 원인 정리 | 최근 실행의 절반 가까이가 실패. 녹색이 돼야 PR 필수 검사로 걸 수 있다 | CI |
| `Payload boot smoke (arm64)` 실패 원인 정리 | 최근 10회 중 9회 실패 | CI·배포 |
| `tools/*.sh`의 하드코딩 Bearer 토큰을 환경변수로 | 공개 저장소에 토큰 문자열이 남지 않게 | 도구 |
| README 「구조」 절을 현재 폴더(`middleware/`, `operations/` …)에 맞추기 | 지금 절은 옛 `src/` 트리를 보여 준다 | 문서 |
| 5MB 넘는 파일 추가를 CI에서 경고 | 큰 바이너리가 이력에 쌓이지 않게 | CI |
| STATUS.md에서 `ROS-SIM HOLD`인 모듈을 시뮬로 올리기 | 장치 없이 게이트를 한 단계 올릴 수 있다 | 각 모듈 |

---

## 6. 소통

| 용도 | 어디 |
|---|---|
| 버그, 할 일, 질문 | GitHub Issues (Projects 보드에서 상태 관리) |
| 코드 리뷰 | PR 코멘트 |
| 회의, 일정, 비공개 자료 | Notion |
| 결정 | ADR (`docs/adr/`) — 말로 정한 것도 계약이면 ADR로 남긴다 |
