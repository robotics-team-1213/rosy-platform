# 보류한 브랜치와 보관한 브랜치 (2026-10-14 기준)

2026-10-13과 10-14에 미병합 브랜치를 한꺼번에 정리했다. 이 문서는 그 결과 가운데 다음 사람이 손댈 수 있는 것을 적는다. 보류는 브랜치가 남아 있고 `main`에 들어가지 않은 것이다. 보관은 브랜치를 지우고 `archive/<날짜>/<브랜치>` 태그만 남긴 것이다(D-172). 이름은 2026-10-14에 `git branch --list`와 `git tag -l`로 확인했다.

정리의 방법과 교훈은 [check-supersession-before-resolving-stale-branch-conflicts](../solutions/workflow-issues/check-supersession-before-resolving-stale-branch-conflicts-2026-10-13.md)와 [a-rule-that-only-works-if-everyone-follows-it-is-not-a-gate](../solutions/workflow-issues/a-rule-that-only-works-if-everyone-follows-it-is-not-a-gate-2026-10-14.md)에 있다.

## 이 태그들은 실험실 clone에만 있다

- 2026-10-13과 10-14의 `archive/` 브랜치 태그 125개(10-13에 100개, 10-14에 25개)와, 커밋되지 않은 작업의 스냅샷 태그 45개(`archive/2026-10-14/wip/<워크트리>`)는 **실험실 PC의 clone 하나에만 있다. origin에는 없다.** 그 PC의 저장소가 사라지면 같이 사라진다.
- **wip 스냅샷은 공개 원격에 push하지 않는다.** 커밋되지 않았던 내용이라 공개 기준(D-226)으로 본 적이 없다. 이 스냅샷은 태그이므로 `git push --tags`와 `git push origin 'refs/tags/*'`가 그대로 내보낸다. 이 저장소에서는 두 명령을 쓰지 않는다.
- 어디에 둘지는 정해지지 않았다. 권장은 비공개 미러다(D-762 「열린 항목」 2).

목록과 되살리기:

```bash
# 목록: 날짜별 브랜치 태그, 그리고 wip 스냅샷
git tag -l 'archive/2026-10-1[34]/*'

# 되살리기: 태그에서 새 주제 브랜치와 워크트리를 만든다(wip 스냅샷도 같은 명령이다)
git worktree add --relative-paths .worktrees/<짧은이름> -b <type>/<topic> archive/<날짜>/<브랜치>
```

되살린 내용을 `main`에 들일 때는 D-172대로 한다. 태그를 그대로 머지하지 않고, 새 주제 브랜치에서 지금의 경로에 맞춰 다시 만들고 독립 리뷰를 거친다.

## 보류 (브랜치가 남아 있다)

"main 대비"는 2026-10-14의 `git rev-list --count main..<브랜치>`다.

| 브랜치 | 끝 커밋 | main 대비 | 결정 | 왜 보류인가 | 무엇이 풀어 주는가 |
|---|---|---|---|---|---|
| `feat/d400-plan2-rosim` | `9a0412d24` | 26 커밋 | D-400 plan 2 | Gazebo 관문을 한 번도 통과하지 못했다 | 사용자가 고른 시각에 시뮬레이션 PC에서 Gazebo 관문을 돌려 통과시킨다 |
| `refactor/d171-track1-port` | `b3e3f9590` | 8 커밋 | D-171 track 1 | 실제 ROS 아래에서 import된 적이 없다. rig A/B 비교가 남아 있다. `control` 패키지가 크기 판정을 43줄 넘는다 | 실제 ROS에서의 import 확인, rig A/B, 43줄을 줄이거나 독립 재판정 |
| `feat/device-power-policy-port` | `01ee95539` | 18 커밋 | D-440 | 파일 세 개를 `safety_modules`에 넣을지 정해지지 않았다. Fleet 크기 여유는 D-753 아래 0줄인데 이 브랜치가 52줄을 더한다. 브라우저 시나리오와 장치는 확인하지 못했다 | `safety_modules` 결정, Fleet 52줄의 추출 또는 독립 재판정, 브라우저 시나리오 실행, 장치 확인 |
| `feat/sd-identity-mode-port` | `8a5068ada` | 1 커밋 | D-746 | PowerShell 경로와 그 시험 4개가 한 번도 실행되지 않았다. 시험 PC에 PowerShell이 없다 | PowerShell이 있는 시험 환경에서 그 4개를 실행한다 |
| `fix/lane-odom-cross-veto-port` | `c7b860464` | 3 커밋 | D-556 | 규칙이 몸이 아니라 앞쪽 선을 잰다. Fleet에 막힘을 묻지 않는다. D-597의 drivable 법칙과 부딪친다 | 다시 설계한다. 이 브랜치를 그대로 들이지 않는다 |

D-440, D-556, D-746은 번호만 선점돼 있고 ADR 본문이 `main`에 없다(`tools/harness/adr_gaps.txt`).

## 2026-10-14에 보관한 25개

태그 이름은 `archive/2026-10-14/<아래 이름>`이다.

### 다른 브랜치로 옮겨 갔다

| 브랜치 | 한 줄 |
|---|---|
| `refactor/d171-track1` | `refactor/d171-track1-port`로 옮겼다(위 보류) |
| `refactor/d171-verified` | 정리 때 "옮겨 감"으로 분류했다. 옮긴 곳은 이 문서를 쓰면서 확인하지 못했다. 되살리기 전에 `refactor/d171-track1-port`와 비교한다 |
| `feat/sd-identity-mode` | `feat/sd-identity-mode-port`로 옮겼다(위 보류) |
| `feat/device-power-policy` | `feat/device-power-policy-port`로 옮겼다(위 보류) |
| `fix/lane-odom-cross-veto` | `fix/lane-odom-cross-veto-port`로 옮겼다(위 보류) |
| `feat/act-native-chain` | 옮긴 작업은 `main`에 들어갔다(`main`의 머지 커밋 `aeaf2a473`). 옮긴 브랜치는 지금 없다 |

### 남은 것이 없거나 뒤의 작업이 대신한다

`main`의 쪽을 택해 충돌을 풀면 더할 것이 남지 않았거나, 뒤에 들어온 작업이 같은 일을 한다. 브랜치별로 어느 쪽인지는 적어 두지 않았다. 되살리기 전에 [supersession 확인](../solutions/workflow-issues/check-supersession-before-resolving-stale-branch-conflicts-2026-10-13.md)의 두 명령으로 다시 잰다.

- `fix/d422-range-min-memory-latch`
- `fix/odom-ns-frame-on-053`
- `fix/face-spi-device-054`
- `fix/device-identity-readback`
- `integrate/gazebo-lane-lap`
- `feat/d428-web-face-sweep`
- `feat/rooms-driver-field`
- `docs/push-generated-1ef859`
- `feat/site-floor-declaration`
- `uiux/operator-shell-fleet`

### 이어 가지 않는다 — 내용은 태그에만 남아 있다

| 브랜치 | 한 줄 |
|---|---|
| `feat/model-valid-rows-gate` | 행을 잘라 학습한 모델이 D-585 기준에서 챔피언보다 낮았다 |
| `feat/image-lane-space` | 시제품. 이미 있는 모듈과 겹친다 |
| `codex/pinky-integrated-current` | 작업 중 스냅샷 |
| `docs/ui-boundaries-d322` | 그 ADR 번호가 다른 결정에 다시 쓰였다 |
| `test/delta-scratch` | 스크래치 |
| `fix/sim-map-pose-binding` | 뒤의 차로 한 바퀴 작업이 대신한다 |
| `fix/camera-effective-law` | 뒤의 차로 한 바퀴 작업이 대신한다 |
| `fix/fleet-close-stop` | 135줄짜리 시험 하나가 `main`에 없다 |
| `test/d507-lane-trip-sim` | SIM 증거 파일 217개가 `main`에 없다 |

2026-10-13에 보관한 100개는 여기에 하나씩 적지 않았다. `git tag -l 'archive/2026-10-13/*'`가 목록이다.
