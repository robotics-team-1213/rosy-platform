# D-742 검수 loopback 현재 결정과 같은 PC 학습 전달

**Status:** Accepted (2026-10-13, 사용자 요청: 파이프라인 연결 및 시험)

## 결정

- 사설 검수 앱의 선택 `--decisions-port`는 localhost의 기존 `/api/decisions` GET만 제공한다. workspace/write token과 쓰기 API는 제공하지 않으며 Host 검사와 no-store를 유지한다. 모델 PC 검수 설치기는 화면 port+10000의 loopback 조회를 함께 설치한다.
- 기존 review_bridge는 선택 `transport: local`에서 같은 PC의 별도 절대 경로로 v2 봉인 자료와 현재 결정을 전달한다. SSH 기본 동작은 유지한다. 링크·변조·다른 기존 자료는 거절하며 임시 복사 후 atomic replace한다. 전달 시각·revision/highwater는 동일한 bridge 원장을 통해 기록한다.
- 기존 ReviewPipeline owner CLI를 사용한다. 승인·원본 pixels·모든 fixed eval·카메라·TTL·철회를 검증하기 전에는 데이터셋 학습 요청과 GPU 실행을 허용하지 않는다. 사람 자료가 아직 없으면 no_approved_masks로 대기한다.
- 릴리스 source와 private config/state/store를 분리한다. D-446/D-561의 서명된 코드와 롤백을 유지한다. UI 작업 결과 연결은 읽기 표시이며 학습 권한이 아니다.

## 관계와 시험

| 계약 | 관계 |
|---|---|
| D-427/D-429 | curation/training/deploy 소유 위치와 기존 bare imports 유지 |
| D-430 | CORE·cmd_vel·장치 admission과 별개. 주행 명령 없음 |
| D-464 | 기존 independent IndexedReview와 persisted transport highwater 재사용 |
| D-446/D-545/D-561 | 모델 PC 서명 릴리스·검수 상태 보존·실패 복구 유지 |

원격 시험은 loopback 쓰기/Host 거절, 같은 PC 봉인 전달과 중복·변조·링크 거절, owner 수용과 TTL·철회·eval 중복을 검증한다. 격리 fixture와 실제 사람 정답/운영 학습 수용은 구별한다.

### Addendum (2026-10-24)

협업 모드(D-757) 앱은 무인증 `--decisions-port`를 열지 않으므로 같은 PC bridge는 `authority.state`로 검수 state의 `reviews.sqlite3`를 SQLite `mode=ro`로 읽는다. 문서는 `/api/decisions`와 같다. 이 보완은 권한 규칙을 지키는 같은 PC state 출처를 추가할 뿐 D-742의 loopback 결정을 뒤집지 않는다. `endpoint`와 `state` 중 하나만 허용하고, 링크·`..` 없는 정규 절대 경로, 같은 `workspace_id`, WAL이 아닌 DB를 요구한다. POSIX에서는 state 폴더·DB·journal 파일이 현재 사용자 소유이고 group/other 권한이 없어야 하므로 무인증 loopback 포트보다 범위가 좁다. 이후 검증·revision·전달 단계는 바뀌지 않는다. 원격 시험 수용이며 모델 PC 운영 수용은 별도다.

| 계약 | 관계 |
|---|---|
| D-757 | 협업 모드는 무인증 decisions-port를 제외한다. 같은 PC bridge는 이 addendum의 state 출처를 쓴다 |
