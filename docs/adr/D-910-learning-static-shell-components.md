## D-910 Learning 검수 문서의 정적 공통 셸

**Status:** Accepted (2026-10-28)

### Context

사용자는 Fleet 밖의 UI/UX도 계속 개선하도록 요청했다. Learning 검수 웹12문서는 브랜드·계정·테마 헤더와5개 전역 메뉴가 같지만 각자 편집하는 사본이다. 현재 공용 CSS와 조작 부품은 유지하면서 편집 원본의 중복을 제거한다.

### Decision

- Learning 소유 `review_app_web/components/header.html.inc`와 `rail.html.inc`가 정본이다. `.html.inc`는 독립 화면이 아닌 합성 조각이다.
- `learning/curation/perception/review_shell.py`는 고정12문서의 고정 슬롯만 합성한다. 문서별 전역 영역의 `aria-current=page`와 하위 문서의 `aria-current=true`, 계정 현재 위치를 고정 매핑에서 보존한다. 로컬 메뉴·업무 폼·화면 API는 합성 대상이 아니다.
- 생성된 정적 HTML을 커밋한다. `--check`와 회귀가 누락/중복 슬롯과 사본 드리프트를 거절한다. 서버와 브라우저에 템플릿 런타임·fetch를 추가하지 않으며 첫 응답부터 셸을 제공한다.
- 기존 D-624/D-639/D-741의 토큰·부품·탐색 배치를 소비한다. 신규 역할 토큰이나 조작 문법은 추가하지 않는다. D-906/D-909의 Fleet 소유 컴포넌트를 Learning에 수입하지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 learning/curation/perception 소유에 둔다. 새 최상위 폴더·서비스 없음 |
| D-429 | 공용 시각 부품과 Learning 문서 배치를 구분한다. 학습/평가 owner 변경 없음 |
| D-430 | CORE·OMX 명령 권한·학습 승격·사람 라벨의 정본을 변경하지 않는다 |

### Consequences

편집은 두 조각에서 하고 저장소 루트에서 `python learning/curation/perception/review_shell.py`로12사본을 갱신한다. `--check`로 일치 여부를 확인한다. 계정 활성 항목과5전역 영역 변경은 정본 한 곳에 적용한다. 기존 URL·CSP·정적 자산 설치·계정 복귀·하위 탐색은 보존한다.

합성/드리프트·첫 응답·활성 메뉴·계정·자료/정답/학습/평가 회귀를 별도로 확인한다. 이 결정은 실제 사람 라벨·로봇·학습 모델·현장 UI 수용의 증거가 아니다.
