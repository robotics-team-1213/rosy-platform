# Account 변경 기록

## 2026-11-02 · uncommitted · D-962 독립 인증 소유 모듈

- 변경: 기존 계정·비밀번호·프로필·grant·세션·OAuth·감사를 독립 모듈로 이동했다. 활성 authority의 열 개 테이블·원자적 회수·계정 식별자를 보존하며 Fleet은 서명 자격을 검증하는 receiver가 된다.
- 증거: `da5aab6c09` 원격 Account/브라우저 279 passed, 공유 클라이언트·수신 66 passed, skip 0/NEW 0. `dd9d55404f` 모듈 소유 표식·크기·중복·독립 import 58 passed. 최종 설치와 실제 사용자 수용은 별도다.
- 경계: 서명 이미지 공유가 프로세스·원장·키 공유를 뜻하지 않는다. Account는 Fleet·ROS를 import하지 않는다. 복구 권한은 보존된 receiver 세션의 최신 서명·온라인 회수 상태를 요구한다.
- CE: 로그인 화면과 개발 모드의 결합 교훈은 공통 solutions에 기록했다. 추가 인증 로직은 코드·회귀 시험·D-962가 설명한다.
- gate 변화: SOURCE·LOCAL GO, 서명 설치 ARTIFACT·운영 수용 FIELD HOLD. ROS-SIM·DEVICE N/A.

## 2026-11-02 · uncommitted · 독립 배포 의존성과 통합 검사 보완

- 변경: Fleet은 `rosy-account==0.1.0`을 별도 배포 의존성으로 요구한다. CI wheel 목록·기존 Fleet 조건부 설치·이미지 시험 구성에 Account를 포함하고 Fleet 배포물의 중복 소유를 없앴다. API 이력 행과 추가 서비스의 로그 제한 검사도 보완했다.
- 증거: `8ec7d66580` API·공개 출처·로그 검사 24 passed. `3286f5528e` 실제 wheel·sdist·설치·CI 관련 24 passed와 기존 실패 네 항목의 격리 재실행 4 passed, isolation complete 4, skip 0/NEW 0. 같은 head의 독립 검토 지적 없음.
- 경계: 과거 공개 Actions pin은 독립 검토로 upstream commit API·태그를 확인한 정확한 과거 commit/path/rule 기록만 사용한다. 비밀 탐지 정책은 바꾸지 않는다. 런타임 인증·grant·장치 제어 계약은 그대로다.
- CE: 추가 패키징 판단은 의존성 선언·실제 설치 회귀 시험이 설명한다. 기존 로그인 화면 교훈 외의 새 교훈은 늘리지 않는다.
- gate 변화: 통합 FULL은 실패 수정 후 재실행 대기다. 서명 산출물 ARTIFACT·운영 수용 FIELD HOLD를 유지한다.
