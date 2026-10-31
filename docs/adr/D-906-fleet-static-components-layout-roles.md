## D-906 Fleet 정적 공통 컴포넌트와 레이아웃 역할 토큰

**Status:** Accepted (2026-10-28)

### Context

사용자는 화면마다 나타났다 사라지는 접속 영역을 제보한 뒤 컴포넌트·토큰 기반으로 하드코딩을 없애고 배치를 맞추도록 요청했다. Fleet 네 문서의 헤더/탐색은 동일하지만 독립 HTML 사본이었고, 지도·Cell의 본문 배치와 피드백 여백도 별도 소유였다. 기존 공용 컨트롤·색·글꼴·권한 계약을 유지하면서 그 중복을 제거한다.

### Decision

1. Fleet의 헤더·전역 탐색은 `applications/fleet/web/shared/fleet-header.html.inc`과 `fleet-nav.html.inc`이 정본이다. `fleet_components.py`가 고정 네 문서의 고정 슬롯만 합성한다. `.html.inc`는 독립 페이지가 아닌 조각임을 표시한다. 생성된 HTML은 첫 HTTP 응답부터 완성되어 있으며 기존 FileResponse·CSP·URL·초기 정지 표시는 그대로다. `--check`와 회귀가 원본/산출물의 어긋남을 거절한다. 클라이언트가 뒤늦게 셸을 삽입하지 않는다.
2. Fleet 공통 배치 컴포넌트는 `shared/doc-tabs.css`가 소유한다. 페이지는 업무별 열·지도/문서 배치를 소유한다. 본문 안쪽 여백과 피드백 기준선을 네 문서에 맞춘다. 지도·SVG의 좌표/선·카메라/물리 단위는 시각 토큰 치환 대상이 아니다.
3. 값의 정본은 `shared/web/tokens.css`다. 다음 역할은 팔레트나 기본 척도를 늘리지 않고 실제 컴포넌트에서만 소비한다. 공용 갤러리는 계산된 값을 읽어 보여 준다.

| 역할 | 값 | 목적 |
|---|---|---|
| `--content-task-max` | 90rem | Cell·지도 절차 본문의 최대 폭 |
| `--inset-task-page` | `--space-4` | 네 본문과 피드백의 공통 안쪽 기준선 |
| `--gap-task-page` | `--space-4` | 작업 본문 묶음 간격 |
| `--gap-task-actions` | `--space-3` | 기존 작업 조작 묶음 간격 |
| `--size-rail-item` | `--target-secondary + --space-2` | 기존 56px 탐색 항목 크기 |
| `--measure-credential-field` | 10rem | 토큰 접속 필드의 유연한 폭 기준 |
| `--measure-login-field` | 9rem | 로그인 필드의 짧은 기본 폭 |
| `--measure-account-label` | 12rem | 헤더 역할 글의 최대 폭 |

4. D-359/D-624/D-639의 공용 토큰·컨트롤 경계와 D-741의 셸·하위 탐색·정지 위치를 유지한다. 새 런타임 프레임워크·외부 의존성·인증/명령 API는 추가하지 않는다.

### Consequences

정본을 편집한 뒤 `python applications/fleet/web/shared/fleet_components.py`로 네 정적 산출물을 갱신한다. 독립적으로 헤더/탐색 사본을 편집하면 check가 실패한다. 생성된 복제는 런타임/최초 화면/설치 산출물을 위한 것이며 별도 설계 원본이 아니다.

본문 inset은 관제/설치의 기존 폭별 값에서16px로 통일한다. 지도/Cell의 기존90rem·16px·actions12px과 rail56px은 유지한다. 기존 1px 경계·접근성 숨김 기법·반응형 임계값·데이터 기하는 역할 값이 같다는 이유로 바꾸지 않는다.

Accepted는 설계 선택이며 실물·현장·배포 수용이 아니다. 정적 조합/누락/중복·드리프트·wheel, JS 없이 받은 첫 문서, 320/390/768/1440 및 경계 상태의 실제 geometry와 키보드 회귀를 별도로 확인한다.
