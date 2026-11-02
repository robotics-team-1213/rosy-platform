# Account 변경 기록

## 2026-11-02 · uncommitted · D-962 독립 인증 소유 모듈

- 변경: 기존 계정·비밀번호·프로필·grant·세션·OAuth·감사를 독립 모듈로 이동했다. 활성 authority의 열 개 테이블·원자적 회수·계정 식별자를 보존하며 Fleet은 서명 자격을 검증하는 receiver가 된다.
- 증거: `da5aab6c09` 원격 Account/브라우저 279 passed, 공유 클라이언트·수신 66 passed, skip 0/NEW 0. `dd9d55404f` 모듈 소유 표식·크기·중복·독립 import 58 passed. 최종 설치와 실제 사용자 수용은 별도다.
- 경계: 서명 이미지 공유가 프로세스·원장·키 공유를 뜻하지 않는다. Account는 Fleet·ROS를 import하지 않는다. 복구 권한은 보존된 receiver 세션의 최신 서명·온라인 회수 상태를 요구한다.
- CE: 로그인 화면과 개발 모드의 결합 교훈은 공통 solutions에 기록했다. 추가 인증 로직은 코드·회귀 시험·D-962가 설명한다.
