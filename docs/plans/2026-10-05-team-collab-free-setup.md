# ROSY 팀 협업 무료 구성안 — GitHub · CI/CD · Notion

**작성:** 2026-10-05 · **상태:** 검토용 안 (실행 전, 아무것도 바꾸지 않음)
**목표:** 팀원과 GitHub 공개 저장소로 같이 개발하고, CI/CD를 돌리고, Notion을 MCP로 편집한다. 전부 0원.

---

## 1. 현재 상태 (2026-10-05 확인)

| 항목 | 상태 |
|---|---|
| 저장소 | `livsbittt/rosy-os` — **PUBLIC**, Apache-2.0, 개인 계정 소유, 협업자 본인 1명 |
| CI | 워크플로 10개 (`ci`, `arm64-rehearsal`, `build-pinky-image`, `build-site-candidate`, `android`, `publish-release` 등) GitHub 러너에서 동작 중 |
| CD | D-437: 빌드는 GitHub 러너, **서명은 로컬 오프라인**. site 후보는 GitHub prerelease (`site-*` 태그) |
| main 보호 | **없음** (Branch not protected) |
| 협업 파일 | PR 템플릿 · 이슈 템플릿 · `CODEOWNERS` · `CONTRIBUTING.md` **없음** |
| 로컬 | 로컬 `main`이 `origin/main`보다 13커밋 앞섬 → 그 커밋들의 CI 증거 없음 |
| 최근 CI | 최근 200회 실행 기준 `ci` 107회 중 **57회 실패**, `Payload boot smoke (arm64)` 10회 중 **9회 실패**. 가장 긴 작업은 이미지 빌드 27분, 캐시 사용 0 |
| 비공개 자료 | `private/`는 gitignore → 팀원에게 전달 경로 없음 |
| 비밀값 | gitleaks 이력 스캔(4068커밋) 93건. 대부분 테스트 픽스처·스캐너 패턴. 단 `tools/*.sh`, `docs/plans/*`에 **하드코딩된 Bearer 토큰 문자열** 있음 |
| 저장소 경로 하드코딩 | `livsbittt/rosy-os`가 main의 22개 파일에 있음. 특히 로봇 자동 업데이트 `deploy/robot/pinky_pro/native/rosy_auto_update.py:75` `DEFAULT_REPO` |

---

## 2. GitHub — 무료 Organization + PR 기반

### 2.1 무료 Organization으로 되는 것

| 항목 | 무료 Org |
|---|---|
| 공개 저장소 수, 팀원 수 | 무제한 |
| 역할 (Read/Triage/Write/Maintain/Admin), Teams 권한 | 가능 |
| Actions (공개 저장소, ARM64 러너 포함) | 무료, 분 제한 없음 |
| main ruleset (공개 저장소) | 가능 |
| Projects, Discussions, Releases, GHCR(공개) | 가능 |
| 불가 | SSO, 감사 로그 장기 보관 등 엔터프라이즈 기능 — 현재 불필요 |

### 2.2 이전 절차

1. github.com → `+` → **New organization** → **Free** → 이름 입력
2. `rosy-os` → Settings → Danger Zone → **Transfer** → 새 org
3. org → **People** 초대, **Teams**로 권한 부여
4. main **ruleset**: PR 필수, `ci` 통과 필수, force-push 금지

### 2.3 이전 시 주의

- 옛 주소 `livsbittt/rosy-os`는 웹·git·API 모두 자동 리다이렉트된다. 같은 이름 저장소를 다시 만들면 끊긴다.
- **로봇 자동 업데이트**(`rosy_auto_update.py` `DEFAULT_REPO`)는 `urllib`이 301을 따라가므로 동작할 것으로 보지만 **이전 직후 업데이트 확인을 실제로 한 번 돌려 본다.** 새 경로로 바꾼 릴리스를 이전과 같이 낸다.
- 하드코딩 22개 파일(문서, Colab 노트북, 릴리스 도구, 테스트)을 한 커밋으로 바꾼다.
- 로컬 remote는 `git remote set-url origin https://github.com/<org>/rosy-os.git`로 갱신.

### 2.4 착지 규칙 변경 (ADR 필요)

지금 「같이 하는 깃」(AGENTS.md, D-372/D-427)은 **한 PC의 `main` 체크아웃 하나를 여러 세션이 공유**하는 전제다. 팀원이 들어오면:

- 정식 경로: 브랜치 → **PR** → CI 통과 → 머지
- 로컬 `--ff-only` 착지는 본인 PC 안의 세션 사이에서만
- 이 변경은 ADR 하나로 결정하고 AGENTS.md · README의 같은 절을 함께 고친다.

추가할 최소 파일: `.github/pull_request_template.md`, `CODEOWNERS`, `CONTRIBUTING.md`(AGENTS.md·README 계약 절 링크만).

---

## 3. CI/CD — 거의 그대로

- 공개 저장소는 표준·ARM64 러너 모두 무료·무제한 → 현 구성 유지.
- fork PR은 `pull_request` 트리거로만 돌고 secret을 못 읽는지 확인. **`pull_request_target` 금지.**
- **로봇·사이트 PC를 self-hosted runner로 붙이지 않는다.** 공개 저장소라 누구나 PR로 장치에서 코드를 실행시킬 수 있다. 장치 게이트는 지금처럼 사람이 수동 실행.
- CD 범위: CI가 unsigned 후보를 prerelease로 올림 → **서명·배포는 사람이 로컬에서** (D-437 유지).

### 3.1 공개 저장소에도 남는 제한

분(minute) 총량은 무제한이지만 다음은 남는다. 막히는 게 아니라 팀이 커지면 **대기가 길어지는** 정도다.

| 제한 | 공개 저장소 무료 | 현재 Rosy |
|---|---|---|
| 실행 분 총량 | 무제한 (표준·ARM64) | 무관 |
| job 1개 최대 시간 | 6시간 | 최장 27분 (이미지 빌드) |
| 동시 job | 20개 (Free 계정·Org 동일) | 팀원 동시 push 시 큐 대기 |
| 캐시 | 저장소당 10GB | 0 |
| artifact 보관 | 최대 90일 | 오래 둘 것은 Release로 |
| Release 파일 1개 | 2GB | 이미지가 커지면 압축·분할 |
| 큰 러너 (다코어·GPU) | **유료** | 미사용. 모델 학습은 OMEN PC |
| self-hosted 러너 | 무료지만 보안상 미사용 | 미사용 |

> 6시간 · 20개 · 10GB · 2GB · 90일은 작성 시점의 GitHub 기준으로 적었고 조회해서 확인한 값이 아니다. 정책이 바뀔 수 있으니 GitHub 문서에서 확인한다.

### 3.2 실제 문제는 실패율

PR에 `ci` 통과를 필수로 걸면, 지금 실패율로는 팀원 PR이 계속 빨간불로 막힌다. ruleset을 켜기 **전에** 다음을 확인한다.

- `ci` 실패 57/107이 브랜치 push가 많아서 생긴 착시인지, main에서 실제로 깨진 것인지 (`gh run list --branch main --workflow ci`)
- `Payload boot smoke (arm64)` 9/10 실패의 원인 — 고치거나, 고칠 때까지 필수 검사에서 뺀다

---

## 4. 공개 전 정리 (가장 먼저)

1. 하드코딩 Bearer 토큰이 로봇·사이트에서 **실제로 쓰이는 값이면 교체**. 이미 공개됐으므로 이력 삭제는 의미 없다. 개발용 기본값이면 스크립트가 환경변수를 읽도록만 바꾼다.
2. CI 실패율 정리 (3.2) — `ci` 57/107, `Payload boot smoke` 9/10. 필수 검사로 걸 workflow를 녹색으로 만든 뒤 ruleset을 켠다.
3. 로컬 13커밋 push → CI 증거 확보.

---

## 5. Notion — 문서 원본은 저장소, Notion은 팀 공간

### 5.1 역할 분담

| 어디 | 무엇 |
|---|---|
| 저장소 (원본) | ADR, SRS, 계약 문서, API reference |
| Notion | 회의록, 일정, 온보딩, `private/` 비공개 자료(현장 주소·접속 정보) — 저장소 문서는 링크만 |
| GitHub Projects | 작업 관리 (이슈·PR 자동 연결). Notion엔 GitHub 연동 뷰만 |

자동 동기화 Action은 만들지 않는다. 필요해지면 그때.

### 5.2 계정 — Google 계정 공유는 하지 않는다

- Google 계정을 공유하면 Notion뿐 아니라 Gmail · Drive · 비밀번호 재설정 권한까지 넘어간다. 2단계 인증 코드도 한 사람 폰으로만 온다.
- 수정 기록이 전부 한 사람으로 남고, 팀원이 빠질 때 권한만 회수할 방법이 없다.
- SaaS 계정은 보통 1인용으로 보는 약관이다(Notion 약관 직접 확인 필요).

**대신:** 본인 워크스페이스에 팀원을 **게스트**로 초대 (무료, 최대 10명, 페이지 단위 권한).
멤버가 2명 이상이면 무료 플랜에 블록 한도가 걸리므로 멤버로 넣지 않는다. 가입 전 현재 요금표 확인.

### 5.3 Notion MCP로 편집 — 연동 토큰 방식 (추천)

1. 소유자가 notion.so/profile/integrations → **Internal integration** 생성 → `ntn_...` 토큰
2. 팀 최상위 페이지 `⋯` → **Connections** → 그 연동 추가 (그 페이지와 하위만 접근)
3. 팀원 각자, 자기 PC의 Rosy 폴더에서 (로컬 범위, `-s user` 쓰지 않음):

   ```bash
   claude mcp add notion -e NOTION_TOKEN=ntn_xxx -- npx -y @notionhq/notion-mcp-server
   ```

| 장점 | 단점 |
|---|---|
| Google 계정 안 넘김, 지정 페이지만 접근 | MCP 수정 기록이 연동 이름 하나로 남음 (사람이 브라우저로 고친 건 각자 게스트 이름) |
| 팀원 이탈·유출 시 토큰 재발급만 | |
| 연동은 멤버가 아니라 블록 한도 영향 없을 것으로 봄 (미확인) | |

> ⚠️ 저장소가 공개다. 토큰을 저장소의 `.mcp.json`·문서에 넣지 않는다. Notion 비공개 페이지나 메신저로 전달.

### 5.4 대안 — 공식 호스팅 MCP + 각자 계정

```bash
claude mcp add --transport http notion https://mcp.notion.com/mcp
```

OAuth로 각자 로그인해 수정 기록이 사람별로 남는다. 단 **게스트 계정이 OAuth에서 남의 워크스페이스를 고를 수 있는지 불확실**하다. 무료 게스트 구성에서는 5.3이 확실하다.

---

## 6. 실행 순서

| # | 할 일 | 비고 |
|---|---|---|
| 1 | 토큰 확인·교체, CI 실패율 정리(3.2), 13커밋 push | 공개 위험 먼저, ruleset 전 녹색 |
| 2 | 무료 Org 생성 → Transfer → ruleset | 같은 때 `DEFAULT_REPO` 갱신 릴리스, 자동 업데이트 실측 |
| 3 | 팀 PR 착지 규칙 ADR + PR 템플릿 · CODEOWNERS · CONTRIBUTING | AGENTS.md·README 같은 절 동시 수정 |
| 4 | Notion 워크스페이스 + 게스트 초대 + 연동 토큰 + `private/` 이관 + GitHub Projects 연결 | |

## 7. 열린 결정

- [ ] Org 이름, 저장소 이름 유지(`rosy-os`) 또는 변경(`rosy-platform`)
- [ ] 하드코딩 Bearer 토큰이 운영에서 쓰이는 값인지
- [ ] Notion 팀원 10명 이내인지 (넘으면 교육 플랜 또는 GitHub Discussions/Wiki)
- [ ] MCP 방식: 연동 토큰(5.3) / 호스팅 OAuth(5.4)
