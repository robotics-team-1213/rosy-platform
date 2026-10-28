# 로컬 착지를 GitHub PR 경로로 옮기기

팀의 공식 경로는 GitHub PR, `ci-result` 필수 검사, squash 병합이다. 절차는 `docs/reference/pr-pipeline.md`(origin/main)가 소유한다.
이 노트북은 GitHub에 게시하지 못해 `tools/land.py`로 로컬 `main`에 착지해 왔다. 로컬 착지 시험은 실험실 PC에서 직렬로 돌아 느리다.
GitHub Actions의 `ci.yml`은 affected 티어와 병렬 matrix가 있어 같은 검증을 나눠 돌린다. 이 문서는 막힌 원인, 사용자가 풀 일, 밀린 작업의 게시 순서, 이후 정상 흐름을 정한다.

## 1. 지금 막힌 원인 (2026-10-18 이 노트북에서 확인)

| 확인 | 명령 | 실제 결과 |
|---|---|---|
| origin 주소 | `git remote -v` | `https://github.com/robotics-team-1213/rosy-platform.git` (fetch·push 모두 HTTPS) |
| HTTPS | `curl -sS -m 10 -o /dev/null -w '%{http_code}' https://github.com` | `curl: (28) Connection timed out after 10002 milliseconds`, 코드 `000` |
| SSH | `ssh -T -o BatchMode=yes -o ConnectTimeout=10 git@github.com` | `git@github.com: Permission denied (publickey).` 종료값 255. 접속은 되고 키만 거절됨 |
| gh CLI | `gh --version` / `gh auth status` | 2.102.0 설치됨. `livsbittt` 계정 keyring 로그인 확인이 시간 초과(HTTPS 차단) |

결론: 네트워크는 SSH(22)만 통과한다. origin이 HTTPS이고 SSH 키가 계정에 없어 push가 불가능하다. `gh`는 API가 HTTPS라 이 네트워크에서는 PR 생성·병합을 못 한다.

## 2. 사용자가 할 일

1. 공개키를 GitHub에 등록한다. 파일은 `C:\Users\SERIGGG\.ssh\id_ed25519.pub`(Git Bash `~/.ssh/id_ed25519.pub`)이고 지문은 `SHA256:mybrpgxIFDNyf6/3rejYz0wPwYejyAGHfmkvp5RcxYw` (ED25519, `seriggg@SERIGGGA`)다. 개인키 `id_ed25519`는 올리지 않는다.
   - HTTPS가 열린 다른 기기(휴대폰 등)에서 GitHub → Settings → SSH and GPG keys → New SSH key → `.pub` 한 줄 붙여 넣기.
2. 등록 확인: `ssh -T git@github.com` → `Hi livsbittt! You've successfully authenticated` 문구.
3. origin을 SSH로 바꾼다(각 클론·worktree가 공유하는 설정이라 한 번만).
   ```bash
   git remote set-url origin git@github.com:robotics-team-1213/rosy-platform.git
   git fetch origin && git ls-remote origin main
   ```
4. PR 생성·병합에 쓰는 `gh`는 GitHub API(HTTPS)를 쓰므로 SSH만으로는 동작하지 않는다. HTTPS가 막힌 동안은 이 노트북에서 push만 하고, PR 생성·squash 병합은 HTTPS가 되는 곳(다른 PC, 휴대폰 웹, 다른 네트워크)에서 한다. 아니면 네트워크 관리자에게 `github.com`·`api.github.com` HTTPS 허용을 요청한다.

## 3. 밀린 로컬 작업 게시

규모(2026-10-18, 이 브랜치 기준 `main`): `git log --oneline origin/main..main | wc -l` = **320**(merge 64, 일반 256). 반대로 `main..origin/main` = 32(오늘 sync merge로 흡수 예정). 공통 조상은 #54(10-16).
`origin/main`의 #80·#81·#82·#85·#88은 이미 로컬 작업의 squash 사본이다. 그 뒤 로컬에서 같은 파일을 계속 고쳐 오늘 sync merge에서 59개 충돌이 났다.

일반 커밋 256개의 주제별 분포:

| 묶음 | 커밋 | 대표 브랜치 |
|---|---|---|
| OMX native(기동·stop IPC·수집·intake·world model, D-778/D-790) | 약 130 | `feat/omx-native-*`, `feat/omx-instance-namespace`, `feat/omx-bounded-commissioning`, `fix/omx-torque-readback`, `feat/omx-preserved-init`, `feat/omx-final-state-check` |
| Fleet 다중 팔 Cell Job·planner(D-779–D-786) | 22 | `feat/per-arm-cell-ledger`, `feat/multi-arm-*`, `feat/mixed-cell-compile`, `feat/mixed-compile-followups` |
| ADR·조사 문서(`docs(adr)` 18 외) | 약 25 | `docs/bimanual-workcell-adr`, `docs/dual-arm-research`, `docs/mixed-palletizing-research` |
| 카메라 보정·학습 화면(D-792) | 11+ | `feat/measured-camera-calibration`, `docs/rosy-learn-camera-reproducibility` |
| 학습 정책 승인 관문(D-793) | 10 | `feat/omx-d793-stage-a`, `feat/omx-policy-governance-v2` |
| 브라우저 회귀·콘솔·앱 UI | 약 15 | `fix/browser-regressions-ready`, `fix/review-app-ui-tokens`, `feat/app-role-clarity` |
| 하네스·착지 도구·경로 | 약 10 | `refactor/remove-hardcoded-paths`(ROSY_SCRATCH), `feat/land-result-cache`, `feat/remote-pytest-parallel` |
| 기타(G1·bimanual sim, Pinky lap goal, topic→cell task) | 나머지 | `feat/bimanual-g1-sim`, `feat/pinky-lap-goal`, `feat/topic-cell-task` |

로컬 브랜치가 서로를 merge해 와서 브랜치별 재생은 깨끗하지 않다. 각 PR은 `origin/main`에서 새 브랜치를 만들고, 해당 묶음의 경로만 로컬 `main` 내용으로 가져온다(`git checkout <로컬-main-SHA> -- <경로>`). 묶음마다 독립 검토와 `ci.yml` 확인을 거친다. 마지막 PR 뒤 `git diff origin/main <로컬-main-SHA>`가 비어야 게시가 끝난다.

순서(앞 묶음이 뒤의 기반):

1. 하네스·착지 도구·경로 정리. 이후 PR의 CI·시험 실행 방식이 여기에 기대므로 먼저 올린다.
2. ADR·조사 문서. 코드 없이 결정 근거만 담는다.
3. Fleet 다중 팔 후속. #81에 들어간 부분을 빼고 차이만 올린다.
4. OMX native를 3–4개 PR로 나눈다(기동·stop → 수집·intake → world model → commissioning·init). #85·#88과 겹치는 부분은 차이만 올린다.
5. 카메라 보정·학습 화면.
6. 브라우저 회귀·콘솔·앱 UI.
7. D-793 학습 정책 관문. OMX에 기대고 안전 경로라 마지막이다.
8. 기타 묶음은 의존이 없으면 아무 때나 올린다.

trailer 처리: 밀린 커밋 중 11개가 `Safety-Review:` trailer를 갖고 있다. squash는 원본 커밋 메시지를 버리므로, 안전 경로 PR은 본문 줄 맨 앞에 실제 독립 검토의 `Safety-Review:`를 다시 적는다. 병합 뒤 `git show -s --format=%B <병합-SHA>`로 trailer를 확인한다(#81→#82, #78→#86 유실 이력). `python tools/harness/safety_review.py origin/main main --warn-only`는 지금 trailer 없는 안전 경로 커밋 2개를 보고한다(`85cfdeb4d8`, `9a8d9ba2cc`, `operations/overhead/rosy_vision/ingest.py`). 5번 PR은 게시 전에 독립 검토를 받아 trailer를 붙여야 CI를 통과한다. 원본 커밋과 squash SHA 연결이 필요하면 독립 검토 후 `tools/harness/safety_review_exempt.json`에 정확한 SHA로 넣는다.

## 4. 같은 충돌을 다시 만들지 않기

squash 사본이 origin에 생긴 뒤에도 로컬 `main`에서 같은 파일을 계속 고치면, 다음 sync에서 두 사본이 충돌한다. 게시가 끝나면 다음처럼 바꾼다.

- 로컬 `main`을 `origin/main`에 맞춘다. 공유 체크아웃 규칙상 임의 reset은 금지라 사용자 승인 후 백업 태그(`git tag backup/local-main-2026-10-18 main`)를 남기고 한 번 수행한다. 조건은 §3의 diff가 비어 있는 것이다.
- 이후 토픽 브랜치는 항상 `origin/main`에서 시작한다. 착지는 PR squash 병합만 쓰고, 로컬 `main`은 `git merge --ff-only origin/main`으로만 따라간다.
- 오프라인 중 `land.py`로 착지한 작업은 연결되는 즉시 PR로 올린다. 병합 뒤 로컬 `main`을 다시 `origin/main`에 맞추고, 그 사이에는 착지된 파일을 새 토픽에서 고치지 않는다.

## 5. 이후 정상 흐름

```text
origin/main에서 토픽 브랜치 → 커밋·로컬 집중 시험 → 독립 검토 → git push(SSH)
→ PR(gh pr create) → ci.yml affected 티어가 GitHub runner에서 병렬 실행 → ci-result 확인
→ gh pr merge --squash --match-head-commit <SHA> --body-file <본문> → trailer·병합 SHA 확인
```

`land.py`와 실험실 PC 직렬 FULL 시험은 오프라인 작업용으로만 남긴다. 실험실 PC는 ROS·Gazebo·장치처럼 GitHub runner가 못 돌리는 검증에 쓴다.

## 6. 위험과 사용자 결정

- HTTPS 차단이 계속되면 push는 되어도 `gh`(PR·검사 조회·병합)를 이 노트북에서 못 쓴다. 다른 기기에서 병합할지, 네트워크 예외를 요청할지 정한다.
- 이 노트북의 개인 SSH 키를 팀 저장소 쓰기에 쓰는 것이 맞는지 정한다. 에이전트 신원 분리(D-762 선행 조건)와 충돌할 수 있다.
- 320개 커밋을 약 10–12개 PR로 나누면 검토 부담이 크다. 묶음 크기와 검토자 확보를 정한다. 경로 단위로 가져오면 커밋 단위 이력과 원본 SHA가 PR 본문 기록으로만 남는다.
- 게시하는 동안 로컬 착지를 멈출지 정한다. 계속 착지하면 §3 diff 기준이 계속 움직인다.
- 로컬 `main` reset(§4)은 되돌릴 수 없는 공유 상태 변경이므로 사용자 승인이 필요하다.
- `ci.yml` full·`modules` 잡에서 밀린 작업의 새 실패가 드러날 수 있다. 실험실 FULL 결과는 GitHub CI 통과의 증거가 아니다.
