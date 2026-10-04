## D-458 학습 앱·웹 공통 작업 화면과 결과 확인 경계

- Date: 2026-10-04
**Status:** Accepted (2026-10-04, 사용자 요청: 학습 관련 앱·웹 전체 점검과 필요한 기능 구현)
- Owner: Pinky 웹앱 전담 세션, feat/pinky-review-web

## Context

D-456의 객체 검수 외 학습 작업은 서로 다른 CLI와 결과 폴더에 있다. 완료 표기가 라벨 승인,
학습 품질 통과, 정책 승격, 로봇 실행 수용 중 무엇을 뜻하는지 화면에서 확인할 수 없다.
사용자는 학습 관련 앱·웹 전체에 필요한 기능을 ADR로 정리하고 구현하도록 범위를 지정했다.

## Decision

기존 로컬 앱에 `/learning` 작업 화면을 추가한다. 새 프로세스나 최상위 소스 영역은 만들지 않는다.
SQLite에 작업 이름·종류·결과 폴더·등록 시 보고서 SHA와 버전을 저장한다. 사진 검수와 양방향으로
이동하고, 작업 필터·새로고침·등록 해제·파일 변경 감지·실패 이유·다음 작업을 제공한다.
등록은 경로 연결이며 학습이나 기존 프로그램 실행을 시작하지 않는다. 해제는 연결만 지운다.
보고서는 현재 파일의 선언 상태로 표시한다. 서명·원본 closure·정책 수용을 대신 검증했다고 주장하지 않는다.
파일이 없거나 손상되면 미확인, 등록 후 바뀌면 변경됨을 표시한다. 서버 재시작 뒤에도 목록을 복원한다.

| 점검 대상 | 현재 기능 | 공통 화면 보완 / 다음 작업 |
|---|---|---|
| 객체 검수·자동 초안 | D-456 영속 검수, 후보 가져오기, 수동 박스 편집 | 현재 승인·대기·제외 개수, 검수 화면 이동, 승인 export와 학습 자격 구분 |
| 영역 검수·자동 마스크 | prelabel/autolabel, CVAT, edge_review_return | 마스크 반환 결과 연결; 객체 승인을 픽셀 승인으로 확장하지 않음 |
| perception 학습 | recording_job/train_job와 단계 receipt | 실행 단계·실패/품질 거절 표시, 원래 CLI의 다음 단계 안내 |
| Pinky 원본·행동 연구 | verify_raw/comparison_job | 원본 검증·research_only 결과 연결; session-disjoint 확인 필요 |
| OMX 시연·ACT 연구 | LeRobot export/act_job | offline_only/reject 상태 연결; joint 단위·독립 평가 확인 필요 |
| 정책 원장 | registry 검증·등록·평가 | 정책 artifact 보고서 확인; 원장 승인 receipt와 owner 권한은 별도 |
| Isaac 학습 환경 | ROS/시뮬레이션 환경, 독립 AGENTS | 공통 기능 목록과 다음 작업 안내; 화면 연결만으로 시뮬레이션을 실행하지 않음 |

D-280의 차분한 지능·은은한 따뜻함과 D-359의 공용 토큰/부품/테마를 그대로 쓴다.
첫 화면에서 전제 조건, 지금 상태, 다음 작업을 읽을 수 있게 한다. 기술 세부 내용은 결과 파일 상세에 둔다.
등록·해제는 local Host/token/origin 보호와 version CAS를 적용한다. 임의 명령·네트워크 호출·모델 로딩은 없다.

| 구조 계약 | 관계 |
|---|---|
| D-427 | learning/training/perception 아래 기존 개발 도구만 확장; 로봇 설치 payload 없음 |
| D-429 | source part 분류·계약 import·기존 작업 CLI 소유권 유지 |
| D-430 | final writer/stop/model activation 권한 없음; safety 경로 변경 없음 |

## Verification

보고서 등록/재시작 복원, 변경·누락·손상·경로 이탈, stale version 해제 거부를 호스트 시험으로 검증한다.
실 Chromium PC/모바일 viewport에서 등록→필터→새로고침→변경 확인→해제와 검수 이동을 실행한다.
운영 승인 자료는 편집하지 않는다. 학습 job 실행, 장치·물리 모바일·CI·현장 수용은 이 검증 범위가 아니다.

로컬 실행 결과: 관련 호스트 59 passed, 순수 박스 기하 4 passed, Chromium 공통 작업 흐름 10개 통과.
실제 결과 4폴더 연결과 서버 재시작 복원, 운영 검수 state 불변을 확인했다.
최종 backend/생성 색인 검사 10 passed; clean baseline에도 재현된 deploy 로그 형식/인코딩 때문에
harness 검사 2건은 실패다. 전체 CI green이나 모듈 gate 승격은 주장하지 않는다.

## Consequences

사용자는 기존 결과 폴더를 한 번 연결해 작업을 확인할 수 있다. 신규 자동 추론/마스크 편집/학습 실행 UI,
CVAT 서버 접속, GPU job scheduler와 정책 승격 UI는 미구현으로 표시한다. 기존 CLI 기능을
웹에서 실행된 기능으로 계산하지 않으며, 그 기능의 소유 세션과 수용 계약을 유지한다.
