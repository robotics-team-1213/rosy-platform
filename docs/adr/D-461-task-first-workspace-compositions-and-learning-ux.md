## D-461 ROSY 작업 화면은 상태·다음 작업·행동을 먼저 보여주고 공용 작업 부품으로 구성한다

**Status:** Accepted (2026-10-04, 사용자 로컬 commit/merge·실제 브라우저 개선·ROSY 디자인 체계 개선 지시)

### Context

학습 화면은 긴 등록 폼과 기술 보고서가 작업 목록보다 앞에 있다. 검색과 확인할 결과만 보는 기능이 없어
반복 작업에서 결과를 찾기 어렵다. 검수 화면의 큰 사진 아래에 박스 편집과 승인 행동이 묻혀 있다.
사용자는 기존 ROSY 디자인 체계도 더 현대적이고 사용자 편의에 맞게 개선하도록 범위를 확대했다.
초기 검수 결정은 번호 충돌 정정 후 D-459, 공통 learning 연결은 D-458이다.

### Decision

공용 디자인의 새 작업 원칙을 DESIGN.md에 기록한다. 상태 → 다음 작업 → 행동 순서,
사용자 언어 우선·세부 증거 펼치기, 주 작업 우선·입력은 필요할 때, 선택/검색 맥락 유지,
키보드·터치에서 같은 작업 완료를 기준으로 삼는다. 로봇 명령·정지·승격 의미는 바꾸지 않는다.

기존 D-359 부품을 합성한 선택형 작업 목록 부품을 shared/web에 추가한다:
`workspace.js`의 텍스트 DOM `taskRow`, `.ui-workspace-bar`, `.ui-task-row/heading/meta/next`.
색·폰트·여백은 기존 토큰에서 읽고 상태 배지는 기존 ui-tag를 사용한다. 기존 화면의 CSS를
덮어쓰지 않으며, 새 파일은 canonical shared-assets.json와 CMake 설치에 함께 등록한다.
새 간격 역할 gap-workspace, inset-workspace-bar, inset-task-row, gap-task-detail은 기존 space 토큰을 참조한다.

| 표면 | 적용 |
|---|---|
| 학습 작업 | 작업 목록 우선, 검색/종류/확인 필요 필터, URL 맥락 복원, 상태·이유·다음 작업, 펼치는 등록 패널 |
| 사진 검수 | 사진 thumbnail 목록, 이전/다음·대기 이동, 사진과 라벨 inspector 병렬 배치, 사진 deep link |
| 기존 ROSY 화면 | 공용 부품을 선택해 쓸 수 있음; 이번 변경만으로 로봇/Fleet 화면 전환이나 DEVICE/FIELD 수용을 주장하지 않음 |

확인 필요는 파일 변경·손상·전체 누락·보고서/단계 거절·실패에서 파생한다. 보고서 완료를
학습 qualification이나 정책 승격으로 바꾸지 않는다. 원본 승인 이력과 현재 운영자 수정은 유지한다.
라벨 저장은 기존 version CAS, 전체 확인 후 명시 승인을 계속 사용한다.

| 구조 계약 | 관계 |
|---|---|
| D-427 | learning 개발 도구와 shared/web 합성 부품만 확장, 새 최상위 part 없음 |
| D-429 | 기존 공용 asset 서빙/설치와 source ownership 유지 |
| D-430 | 명령 writer/stop/모델 활성화 변경 없음, 새 safety 권한 없음 |

### Verification and consequences

계획은 docs/plans/2026-10-04-learning-web-ux-design.md에 기록한다. 실제 Chromium에서 PC/모바일,
dark/light, 검색/필터 유지·빈 상태·등록/오류·해제, 검수 이동·숫자/drag/touch·취소·저장·승인
시나리오를 실행한다. 운영 자료는 읽기만 하고 별도 test state에서 변경 시험을 한다.
첫 묶음 검사 뒤 발견 문제를 한 번에 수정하고 최종 묶음으로 확인한다.
브라우저 LOCAL 결과를 사람 G3·물리 모바일·CI·현장 결과로 보고하지 않는다.
