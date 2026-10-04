## D-456 Pinky 학습 검수는 저장되는 웹앱으로 제공하고 자동 초안·수동 정답·학습 수용을 분리한다

**Status:** Accepted (2026-10-04, 사용자 웹앱 구현·디자인 철학·기능 테스트·자동/수동 라벨링 ADR 기록 요청). 구현 소유는 지정된 기존 웹앱 세션 하나다. 착지·push·배포·모델 활성화·로봇 동작 승인이 아니다.

### Context

파일형 검수 HTML은 새로고침하면 편집을 잃고 사람이 JSONL을 다운로드해서 옮겨야 했다. 사용자는 Pinky 전용 애플리케이션과 기존 ROSY 디자인 철학에 따른 기능 검증을 요청했다. 학습 세션은 자료 준비와 후속 학습 반영을 소유하고 웹앱을 중복 구현하지 않는다. 객체 사진 1·2·4는 기존 박스대로 승인됐고 3은 제외됐다. 이 승인은 벽·차선·횡단보도의 픽셀 정답에 적용되지 않는다.

### Decision

1. **디자인 철학은 D-280의 차분한 지능에 은은한 따뜻함이다.** 사진·상태·다음 행동을 먼저 보인다. 승인·제외·대기는 글로 구별하고, unknown 신호를 임의 색으로 확정하지 않는다. D-359의 `shared/web/tokens.css`, 공용 필드·버튼·태그와 dark/light 테마를 재사용한다. 장미색은 ROSY 이름에만, 박스는 series 색에 쓴다. compact/medium/wide에서 PC·터치·키보드 흐름을 검증한다.
2. **사진 선택 → 라벨 수정 → 전체 확인 → 승인/제외 → 자동 저장 → 승인 자료 준비**가 일상 흐름이다. 수정마다 서버 SQLite 트랜잭션과 이력에 기록한다. 원본 사진과 JSONL은 불변 스냅샷으로 묶는다. 새로고침과 서버 재시작은 같은 workspace를 복원한다. 초기 import는 기존 저장 내용을 덮어쓰지 않는다.
3. **자동 라벨은 후보다.** D-379의 LiDAR/궤적 기하 자동 라벨링과 D-423 `objects` 후보, 기존 모델/시각 초안은 출처를 보존해서 수동 검수에 넘긴다. 앱의 원본 초안 가져오기는 승인 없이 대기로 전환한다. 측정 자료 없는 사진에 기하 라벨을 꾸며내지 않고, 학습된 모델이 없는 상태에서 새 추론을 실행했다고 표시하지 않는다. 현재 앱은 기존 후보/초안 import를 지원하며 자동 라벨 재생성 job과 모델 추론 job 실행 UI는 후속 범위다.
4. **수동 라벨은 명시 검수를 거친다.** 박스 그리기·추가·삭제·좌표 경계 수정·한국어 클래스명/영어 ID·신호 상태를 지원한다. 미분류 후보는 승인할 수 없다. 클래스·박스·신호를 바꾸면 승인과 전체 확인을 해제한다. 빈 박스 리스트를 negative로 만드는 것은 전체 확인 후 명시 승인에만 허용한다. 제외는 `pending_human`, `complete_frame_review=false`, `disposition=excluded_by_user`로 전달하고 빈 negative 라벨을 만들지 않는다.
5. **다른 탭과 다른 사진의 승인을 섞지 않는다.** 쓰기는 현재 version과 일치해야 한다. 오래된 version은 HTTP 409와 재불러오기 안내를 반환하며 최신 내용을 덮어쓰지 않는다. 사진 load generation을 구별하고 이전 사진 callback을 버린다. 사진이 준비되기 전·저장 중·충돌 후에는 승인을 막는다. 실제 크기·hash와 유한 bbox·경계를 검증한다.
6. **영역 라벨은 별도 검수다.** 벽·차선·횡단보도는 기존 CVAT와 `edge_review_return.py`/`build.py` 경로를 유지한다. 이번 앱은 픽셀 마스크 편집·CVAT 서버 연결·영역 승인 기능을 구현했다고 주장하지 않는다. 객체 라벨 승인으로 영역 승인을 생성하지 않는다.
7. **자료 준비와 학습 수용을 분리한다.** `review_return.receive_review`를 직접 호출해 실제 원본 크기 그룹별 YOLO 객체 라벨·불변 입력·hash manifest·COMPLETE를 만든다. export별 frame version과 제외 index를 기록한다. 학습 세션은 `build.py`의 session-disjoint 분할과 모든 고정 평가 세트 `--exclude-eval` 계약을 확인한다. 세션 식별/평가 제외 증거가 없으면 `training_dataset_qualified=false`와 HOLD를 유지한다. 앱은 trainer, publish, 모델 전달/활성화 API를 제공하지 않는다.
8. **로컬 개발 도구의 API다.** loopback 전용 HTTP이며 아래 경로는 CORE/로봇/Fleet wire가 아니다. 같은 origin·Host와 workspace token 검사로 외부 사이트의 쓰기를 거부한다. 사용자 인증 서버·원격 접근·서비스 배포는 별도 결정이다. 인증된 검수자 신원은 미확인이다.

| 기존 구조 결정 | 이번 적용 |
|---|---|
| D-427 learning/operations/middleware | 소스는 기존 `learning/training/perception/dataset`와 그 테스트에 둔다. 새 최상위 파트·로봇 설치 항목을 만들지 않는다. |
| D-429 판단·제어·통신 관심사 | 학습 검수 UI와 로컬 저장은 학습 도구 소유다. CORE 판단/제어 API와 통신 계약을 변경하지 않는다. |
| D-430 안전 분리 | safety anchor·cmd_vel·E-stop·모델 운용 writer를 수정하거나 호출하지 않는다. host browser 결과는 DEVICE/FIELD 수용을 뜻하지 않는다. |

### Local application contract

| Method/path | 동작 |
|---|---|
| `GET /` | Pinky 학습 검수 화면 |
| `GET /api/workspace` | frames(원본·review·status·version), classes, 최신 exports, 로컬 쓰기 token |
| `GET /api/images/<index>` | 저장된 hash와 일치하는 원본 사진 |
| `POST /api/frames/<index>` | `version`, `action`: save(boxes), approve(complete_frame_review=true), exclude, reopen, candidates |
| `POST /api/prepare` | 현재 저장된 review snapshot을 기존 receiver로 검증·export; 학습 qualification은 별도 |

POST는 `X-Pinky-Token`이 필요하다. 승인 요청에 새 boxes를 받지 않고 먼저 저장된 라벨을 승인한다. source hash·크기·index는 클라이언트가 바꿀 수 없다. 400은 잘못된 라벨/입력, 403은 Host/token/origin 거부, 409는 version 충돌이다.

### Functional verification and acceptance

| 검증 | 요구 증거 |
|---|---|
| 영속성 | 실제 브라우저 수정→서버 version 증가→새로고침과 서버 재시작 후 동일 라벨 |
| 승인 범위 | 운영 workspace 1·2·4 승인/3 제외·unknown 신호 보존; 테스트용 승인 기록은 별도 workspace |
| 수동 편집 | 박스 추가/그리기/삭제/좌표·클래스·신호 변경 후 미승인, 전체 확인 후 명시 승인 |
| 자동 초안 | 기존 후보 import가 대기로 남음, 분류 없는 후보 승인 거부, 출처 표시 |
| 동시성 | 두 탭의 stale write 409, 최신 라벨 보존, 충돌 후 재불러오기 |
| 사진 전환 | 늦은 image load에서 이전 callback 무시, loading/error 상태 승인 비활성 |
| 원본/학습 경계 | hash/실제 크기/bbox 거부, 제외 라벨 미생성, mixed-size export와 COMPLETE 검증, session/eval qualification HOLD |
| UX | PC 및 모바일 viewport의 실제 Chromium 실행·스크린샷, overflow·키보드·dark/light·콘솔 오류 검증; 실물 모바일 기기 시험과 구별 |

### Alternatives and consequences

다운로드 HTML은 저장·충돌·자료 전달을 사용자에게 맡기므로 기각했다. CVAT 전체 서버를 새로 배포하는 선택은 객체 4장 검수에 필요한 운영 부담이 커 이번 범위에서 제외했다. 기존 receiver와 표준 SQLite를 재사용하는 로컬 앱을 선택한다. 픽셀 편집, 자동 job 실행, 인증 서버와 원격 서비스 운영은 미구현이며 후속 소유와 증거가 필요하다. 구현·검증 상태는 담당 세션의 handoff/status와 테스트 결과에서 확인한다.
