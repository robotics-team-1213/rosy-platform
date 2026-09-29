## D-339 화면 제목과 폴더 이름은 역할을 드러낸다 — 패키지 이름은 그대로 두고 대응표를 시험으로 고정한다

**Status:** Accepted (2026-09-29, 표시 이름·폴더 경로·대응표만). ROS 패키지 이름, 실행 파일, launch, systemd 유닛, 이미지 내용은 바꾸지 않는다(D-231).

### Context

폴더와 ROS 패키지 이름이 다른 곳이 일곱 곳이다.

| 폴더 | 패키지 |
|---|---|
| `runtime/gateway` | `core` |
| `runtime/sensing` | `control` |
| `runtime/services` | `core_features` |
| `runtime/api_web` | `core_api_web` |
| `contracts/foundation` | `core_common` |
| `hmi/face` | `emotion` |
| `hmi/web` | `web_common` |

D-231은 패키지 이름을 바꾸지 않기로 했다. 이미지·systemd 유닛·`ros2 run` 호출과 진행 중인 많은 작업 브랜치가 이 이름을 쓰기 때문이다. 그런데 이 대응은 `src/AGENTS.md` 산문에만 적혀 있고 검사가 없다.

웹 쪽에는 이름이 역할을 가리는 곳이 두 군데 있다.
- 공용 자산 라이브러리 폴더가 `hmi/web`이다. 사람이 여는 화면처럼 읽힌다.
- PARKED 제어 진단 페이지 파일이 `runtime/sensing/web/dashboard.html`이다. 운용자 화면 패키지 `dashboard`와 이름이 겹친다.

브라우저 탭 제목도 제각각이다. `Rosy OS — Field Runtime`, `Rosy control diagnostic`, `Rosy Fleet — 사이트 관제`, `Rosy 경기 보드`, `Rosy 라이브 미션`처럼 로봇·사이트·시뮬 중 어느 쪽 화면인지 제목으로 알 수 없다.

### Decision

1. **패키지 이름은 그대로다.** 폴더가 역할 이름이고, 폴더와 패키지가 다르면 그 대응을 `test/architecture`의 시험이 `package.xml`과 대조해 고정한다. 새 폴더를 만들 때는 폴더 이름을 역할로 짓고, 패키지 이름이 다르면 같은 커밋에서 대응표에 올린다.
2. **공용 자산 라이브러리 폴더를 패키지 이름과 맞춘다.** `src/hmi/web` → `src/hmi/web_common`. 화면이 아니라 여러 화면이 쓰는 라이브러리라는 점을 폴더에서 드러낸다. 패키지 이름·설치 경로(`share/web_common`)·URL(`/common/*`)은 바뀌지 않는다.
3. **제어 진단 페이지 파일 이름을 역할대로 바꾼다.** `src/runtime/sensing/web/dashboard.html` → `diagnostic.html`. `dashboard`라는 이름은 운용자 화면 패키지(`src/hmi/dashboard`)에만 쓴다.
4. **브라우저 제목은 `Rosy <범위> — <화면 이름>`으로 쓴다.** 범위는 `surfaces.yaml`의 `surface` 값에 대응한다(`robot`→로봇, `site`→사이트, `sim`→시뮬).

   | 파일 | 제목 |
   |---|---|
   | `src/hmi/dashboard/index.html` | `Rosy 로봇 — 대시보드` |
   | `src/hmi/dashboard/surface.html` | `Rosy 로봇 — {{title}}`(운용·작업 준비·설치·정비) |
   | `src/runtime/sensing/web/diagnostic.html` | `Rosy 로봇 — 제어 진단` |
   | `src/site/fleet/fleet/server/web/index.html` | `Rosy 사이트 — 관제` |
   | `src/site/games/games/web/index.html` | `Rosy 사이트 — 경기 보드` |
   | `src/sim/gz_sim/scripts/lane_live_view.html` | `Rosy 시뮬 — 라이브 미션` |

   참조용 페이지(`styleguide.html`, `template.html`)는 표면이 아니므로 규칙에서 뺀다(D-306). 새 표면은 `surfaces.yaml`에 등록할 때 이 규칙을 따르고, 시험이 등록된 표면의 제목을 검사한다.
5. **앱 셸과 네이티브 앱의 자리는 D-337을 따른다.**

### Alternatives

- **패키지까지 역할 이름으로 바꾼다.** 거부한다. D-231이 적은 비용(호출 수백 곳, 장치 유닛, 이미지)이 그대로 남아 있다. 진행 중인 작업 브랜치와도 충돌한다.
- **폴더도 그대로 두고 문서만 고친다.** 거부한다. `hmi/web`과 진단 `dashboard.html`은 읽는 사람을 실제로 헷갈리게 하는 이름이다. 경로만 바꾸면 되는 싼 변경이다.

### Consequences

- 폴더 이동은 경로 참조만 고친다. 예: `surfaces.yaml`, 시험의 COMMON 경로, Fleet·games·sensing의 소스 트리 fallback, 살아 있는 `AGENTS.md`.
- 과거 ADR·계획·검증 기록 속 옛 경로는 역사로 두고 고치지 않는다.
- 진행 중 브랜치가 `src/hmi/web`에 새 파일을 더하면 병합 때 디렉터리 이동 충돌이 난다. 새 경로로 옮기면 된다.
- `test/test_control_launch_boundary.py`처럼 옛 제목을 검사하던 시험은 새 제목으로 바꾼다.

### Validation

`test/architecture`의 폴더↔패키지 대응 시험과 `src/hmi/web_common/test`의 표면 제목 시험. 영향받는 host pytest 묶음이 통과해야 한다. 이 변경은 SOURCE/LOCAL 증거이며 이미지·장치 수용이 아니다.

### References

[D-231](D-231-layered-source-roots-keep-package-names.md), [D-243](D-243-operator-screens-live-in-hmi.md), [D-306](D-306-surface-ownership-and-uiux-closure.md), [D-317](D-317-control-and-shared-contract-source-boundaries.md), [D-329](D-329-surface-registry-and-visual-baseline.md), [D-337](D-337-app-shell-wraps-web-surfaces.md).
