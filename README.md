# ROSY Platform

어떤 로봇이든 웹·표준 API로 제어하고, 현장 Fleet이 여러 대에 미션을 나눠 주는 로봇 플랫폼이다.
ROS 2 Jazzy 기반이며 첫 하드웨어는 Pinky Pro다.
[pinky_pro](https://github.com/pinklab-kr/pinky_pro)를 포크해 전면 리네임했다(D-16). Apache-2.0.

## 어디서 시작하나

| 나는 | 여기부터 |
|---|---|
| 새로 합류한 팀원 | **[팀 가이드](docs/reference/team-guide.md)** — 첫날 설정, 공유 범위, 작업 방식, 맡을 일 |
| PR을 올리려는 사람 | [기여 안내](.github/CONTRIBUTING.md) |
| 빌드·시뮬·테스트·Pi 배포를 하려는 사람 | [개발 가이드](docs/reference/developer-guide.md) |
| 지금 무엇이 되고 안 되는지 보려는 사람 | [STATUS.md](STATUS.md) — 모듈별 게이트 |
| 실험실 PC의 공유 체크아웃에서 일하는 AI 세션 | 아래 「같이 하는 깃」과 [AGENTS.md](AGENTS.md) |

## 문서 지도

| 문서 | 무엇 |
|---|---|
| [CONCEPTS.md](CONCEPTS.md) | 공통 용어 |
| [PRODUCT.md](PRODUCT.md) | 누구를 위한 제품인가 |
| [DESIGN.md](DESIGN.md) | 화면 디자인 규칙 |
| [CORE SRS](docs/spec/ROSY%20CORE%20SRS.md) · [FLEET SRS](docs/spec/ROSY%20FLEET%20SRS.md) | 로봇·현장 서버 요구사항 |
| [API & Protocol Reference](docs/reference/ROSY%20API%20&%20Protocol%20Reference.md) | 외부 API·프로토콜 계약 |
| [ADR Log](docs/reference/ROSY%20ADR%20Log.md) · [docs/adr/](docs/adr/) | 결정 기록 |
| [docs/architecture/](docs/architecture/) | 목표 아키텍처 |
| [docs/deployment/](docs/deployment/) · [deploy/site/README.md](deploy/site/README.md) | 로봇·현장 배포 절차 |
| [docs/solutions/](docs/solutions/) | 지난 문제의 해결 기록 |
| [docs/index.md](docs/index.md) | 전체 문서 색인(생성됨) |

문서끼리 다르면 SRS·API reference·ADR이 이긴다.

## 같이 하는 깃

여러 세션이 이 저장소의 `main` 체크아웃 하나와 git 인덱스 하나를 같이 쓴다.
GitHub에 보이는 이 절이 착수 순서의 공개 기준이다. 같은 규칙의 명령 전문은
`AGENTS.md`의 「같이 하는 깃」에 적는다. 문구를 바꿀 때는 두 절을 한 커밋에서
같이 고친다. 실험실 PC의 우산 문서 `F:\Dev\Control\Robot\Rosy\Agents.md`도
같은 절차를 적는다. 명령 카드는
[`.claude/skills/rosy-land-on-main/SKILL.md`](.claude/skills/rosy-land-on-main/SKILL.md)다.
브랜치 이름과, 남의 미커밋을 지우지 않는 이유는
[D-372](docs/adr/D-372-topic-branch-names-and-shared-checkout-wip.md)다.

제품 파일을 고치기 전에 1번과 2번이 끝나 있어야 한다. 끝난 기준은 `git worktree list`에
자신의 `.worktrees/<짧은이름>`이 있고, 그 디렉터리의 브랜치가 `main`이 아닌 것이다.

1. **작업 위치를 만든다.** 저장소 루트에서 `git status --short --branch`와
   `git worktree list`를 본 다음
   `git worktree add --relative-paths .worktrees/<짧은이름> -b <type>/<topic> main`
   을 실행한다. `<type>`은 내용과 맞는 `feat`, `fix`, `refactor`, `docs`, `uiux`
   가운데 하나다(D-372). worktree는 이 저장소의 `.worktrees/`에만 둔다. 공유
   `main` 체크아웃은 `git merge --ff-only`로 착지할 때만 쓴다. 거기에 커밋되지
   않은 변경을 남기면 다른 세션의 fast-forward가 거절된다. 스크래치, 로그,
   pytest 출력은 저장소 밖에 둔다. 실험실 PC에서는 `X:\DevTemp`다.
2. **자기 경로만 스테이징한다.** `git add`에는 이번 작업에서 자신이 만든 경로만
   적는다. `git add -A`, `git add .`, 디렉터리 단위 add는 쓰지 않는다. 인덱스
   하나가 모든 세션의 것이라 넓은 add 한 번이 다른 세션의 파일을 커밋에 넣는다.
   자신이 쓰지 않은 경로는 그대로 둔다. stash, revert, checkout, restore, reset,
   clean, amend, 삭제로 치우지 않는다. 루트의 추적되지 않은 `list.txt`는 로컬
   메모라 커밋하지 않는다. 머지나 체크아웃이 그 파일 때문에 거절되면 파일을
   그대로 두고 거절 문구를 사용자에게 알린다.
3. **계약을 읽고 고친다.** 제품 파일을 고치기 전에 아래 「핵심 계약」과
   `AGENTS.md`의 Working In This Directory를 읽는다. 외부 API, 모드, 프로토콜
   필드는 그 문서가 가리키는 SRS, API reference, ADR에 있는 것만 쓴다. 읽기가
   끝난 기준은 바꾸려는 경로의 모듈 `AGENTS.md` 또는 해당 ADR을 연 것이다.
4. **ADR 번호는 파일을 만들기 직전에 다시 고른다.** 다른 세션이 몇 분 사이에
   같은 번호를 가져간다. `docs/adr`, ADR Log의 `| D-nnn |` 행,
   `tools/harness/harness.yaml`의 `adr_gaps`, 다른 브랜치의 `docs/adr`를 보고
   빈 번호의 다음을 쓴다. ADR 파일과 Log 행은 한 커밋이다. 조회 명령은
   `AGENTS.md`의 「같이 하는 깃」 4번에 적혀 있다.
5. **테스트는 기존 실패와 비교한다.** 워크트리에서 관련 pytest 결과를 저장소
   밖의 `run.txt`에 남기고 `python test/known_failures.py`에 그 파일을 넘긴다.
   실험실 PC의 경로는 `X:\DevTemp\<이름>\run.txt`다. exit 1의 `NEW`는 그
   브랜치의 실패다. 고친 실패의 줄은 같은 커밋에서 `test/known_failures.txt`에서
   뺀다. 그 브랜치가 만든 실패를 그 파일에 넣지 않는다. 호스트 pytest 통과는
   장치, ARM64 이미지, 현장 수용을 대신하지 않는다.
6. **착지와 푸시는 사용자가 말한 뒤에만 한다.** 착지는 워크트리에서 `git merge main`을
   하고 관련 테스트를 다시 돌린 다음, `main` 체크아웃에서
   `git merge --ff-only <브랜치>`를 한다. `--ff-only`가 거절되면 그 문구를
   알리고, 다른 세션 파일을 치운 뒤 다시 시도하지 않는다. 푸시 순서는 `AGENTS.md`의
   D-427 4항이다. `git fetch` 하고 `origin/main` 위로 rebase 한 뒤
   `python tools/harness/rosy_harness.py generate`를 하고, pre-push 검사를
   통과한 다음에 push 한다. force-push는 하지 않는다. 로컬 `main`이
   `origin/main`보다 앞에 있으면 그 커밋의 CI 증거는 아직 없다.

착수 다음에 손댈 제품 규칙은 아래 「핵심 계약」이다.

## 핵심 계약

아래 불변식은 코드와 문서 전체에서 성립한다. 변경하려면 대응 SRS·API reference·ADR를
먼저 읽는다.

- **CORE 단일 게이트웨이** — 외부 클라이언트는 ROS를 직접 쓰지 않고 CORE API로만
  말한다(CORE SRS §1.3). `core`(`middleware/core/gateway`)가 유일한 외부 접점이다.
- **유일한 `cmd_vel` publisher** — Command Manager(`core_features.command`)만 최종
  주행 명령을 발행한다(D-2). `control`(`middleware/perception`)의 legacy 최종
  publisher는 CORE와 병행하지 않는다.
- **단일 프로세스** — CORE는 한 프로세스에서 메인 스레드 rclpy `MultiThreadedExecutor`,
  워커 스레드 uvicorn+FastAPI로 돈다(D-1). 진입점은 `ros2 run core core`.
- **폴더는 역할 분류** — 디렉터리 경로가 writer 권한·호스트 배치·이미지 closure를
  결정하지 않는다(D-315). 실제 패키지 소비와 설치 묶음은 `deploy/`와 각
  `package.xml`로 확인한다.
- **공개 저장소 경계** — 이 저장소는 공개다. 실제 장치 주소·계정·채워진 장치 설정은
  gitignored `private/`에 두고 공개 문서에는 `<robot-ip>` 표기를 쓴다(D-226).
  날짜 증거는 `docs/validation/<topic>-<YYYY-MM-DD>/`, 모듈 안내은 해당 모듈의
  `docs/` 하나에 둔다.

## 라이선스

[Apache-2.0](LICENSE). [pinky_pro](https://github.com/pinklab-kr/pinky_pro) 포크에서 전면 리네임(D-16)으로 파생되었다.
