# D-937 제품 앱 입사 문법 — 제품·기능 두 레인과 네 제품 원형, 웹 표면 전체 등록

**Status:** Accepted (2026-10-31, 사용자 합의에 따른 입사 문법 정리). 문법·등록 결정이며 물리 이동·권한 변경을 수반하지 않는다.

### Context

`applications/`는 D-822(Fleet), D-876(Monitoring)을 거치며 제품 앱 홀더로 자리 잡았고 Learning은 D-874·D-891로 계산 호스트형 신뢰 경계가 완성됐다. 새 제품이 언제든 들어올 수 있는데, 새 표면이 어느 폴더에 들어가는지는 문법이 아니라 사례와 `surfaces.yaml`·`platform_parts.yaml` 관례로만 전달된다. 등록 누락은 실제 사고를 만든다. 2026-10-18 `review_app_web` 미등록으로 shared/web 계약 시험이 선택되지 않아 main가 빨간불이 됐고(`docs/solutions/workflow-issues/landing-blockers-cost-hours-2026-10-18.md`), 이번 조사에서 `tools/capture/multi_record.html`(토큰을 소비하는 웹 페이지)가 같은 결함류로 미등록인 것을 확인했다.

### Decision

1. **두 레인 판별.** 새 웹·네이티브 표면은 먼저 제품인지 기능인지 판정한다. 기능 표면은 소유 모듈 곁에 두고 `surfaces.yaml`에 등록한다(로봇 화면 `middleware/robot_ui`, 경기 보드 `operations/apps/games`, 학습 검수 앱 `learning/curation/perception/review_app_web`, 녹화 벽 `tools/capture`). 제품 표면은 `applications/<제품>`에 둔다.
2. **네 제품 원형.** 제품 표면은 아래 원형 하나로 입사한다.

| 원형 | 사례 | 형태 |
|---|---|---|
| 거래형 | Fleet (D-822) | 원장·admission을 소유한 사이트 서비스가 자매 화면을 설치·제공 |
| 관측형 | Monitoring (D-876) | 읽기 전용 수집 서비스 + 자매 화면. 쓰기 권한 없음 |
| 계산호스트형 | Learning (D-874·D-891) | 계산 호스트 도구 + 콘솔 허브 진입(`learning_entry`) + 승인은 Fleet. `applications/` 홀더를 만들지 않는다 |
| 외부업무형 | Harbor (D-836) | 별도 저장소, Fleet HTTP 소비, candidate admission |

3. **웹 표면 전체 등록.** 모든 웹 표면은 `surfaces.yaml`에 등록한다. `tools/`의 로컬 페이지도 포함한다. 첫 적용으로 `capture-wall`(다중 녹화 벽, `tools/capture/multi_record.html`)을 등록하고 페이지를 표면 계약에 맞춘다 — 참조 `./` 접두(해석 변화 없음), 범위 제목, 캔버스 색·글꼴을 공용 팔레트(`window.RosyPalette`)로 읽기. `multi_record.py`는 `ui.js`와 의존 모듈 셋을 세션 `common/`에 함께 복사한다.
4. **Learning 웹 carve 조건.** `learning/curation/perception`의 기능 라우트 모듈(`*_web.py`)이 하나 더 늘거나 등록 파일이 600줄에 근접하면 D-750식 server carve를 적용한다. 지금 옮기지 않는다.
5. **불변.** `platform_parts.yaml` 소유권, 설치 신원, 권한 경계는 그대로다. 이 ADR은 새 표면·제품의 입사 판별과 등록만 정한다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | part 구조·불변 소유 ID를 유지한다. `applications/`는 레이아웃 홀더다 |
| D-429 | concern과 API/import 방향을 유지한다. 등록이 권한을 추가하지 않는다 |
| D-430 | 안전 체인·단일 writer·정지 의미를 바꾸지 않는다 |
| D-822 | 거래형 원형의 정의를 계승하고 새 제품 판별로 일반화한다 |
| D-876 | 관측형 원형으로 명명한다 |
| D-874·D-891 | 계산호스트형의 신뢰 경계를 유지한다 |
| D-836 | 외부업무형 원형으로 명명한다 |
| D-329 | 표면 등록의 정본 레지스트리다. 전체 등록으로 보강한다 |
| D-738 | 폴더 한 권한 규칙을 유지한다 |

### Consequences

새 표면을 더하거나 빼는 커밋은 `surfaces.yaml`을 같은 커밋에서 고친다(D-329). `capture-wall` 등록으로 `shared/web` 토큰·테마 변경이 이 페이지를 포함한 계약 시험을 선택한다. Learning 웹 carve는 별도 착지다. 소스·시험 수준의 결정이며 배포·장치 수용을 뜻하지 않는다.
