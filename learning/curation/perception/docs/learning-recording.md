# 로컬 팔·카메라 시연 녹화

Fleet PC 또는 Learning이 설치된 PC의 `/learning/record`에서 구성을 저장하고 시연을 녹화한다. 이 작업대는 기존 소유자가 낸 상태·수락 참조와 카메라 관측을 읽는다. 모터 명령, 버스 점유, 카메라 서비스 전환은 하지 않는다.

현재 확인된 실물 팔의 등록된 동작 참조 피드는 준비되지 않았다. 아래 설정은 생산자를 설치하거나 두 작업 팔의 실물 녹화를 수용하는 절차가 아니다. 영상 미리보기와 `ready` 표시는 녹화 시작 전 검사 자료이며 이동 허가가 아니다.

녹화는 원본 저장소에 1 GiB 여유를 남기고, 변환 시작에는 자료·ZIP용 5 GiB 여유가 필요하다. 저장 오류가 나면 회차를 무효 처리하며 원본은 삭제하지 않는다. 상태 DB까지 쓸 수 없으면 화면의 종료 상태는 메모리에만 남는다. 공간을 확보하고 앱을 재시작한 뒤 확인한다. 다른 회차를 녹화 중일 때는 보관·제외·변환·전달을 실행하지 않는다. 변환을 시작한 세션의 회차는 고정되며 새 녹화는 새 세션에서 시작한다.

## 실행 설정

기존 review state로 실행한다. 새 작업대만 최초 실행에 `--empty-training`을 추가한다. 경로 자리표시는 운영자가 선택한 절대 경로로 바꾼다. 설정·원본·보정 자료는 Git 밖에 둔다.

```bash
python learning/curation/perception/review_app.py --state "<absolute-review-state>" --recording-config "<absolute-recording-config.json>"
```

녹화 설정 예시:

```json
{
  "schema": "rosy.learning.recording-config/1",
  "host_id": "<local-host-label>",
  "source_root": "<absolute-local-source-registry>",
  "sources": [],
  "export_python": "<absolute-pinned-exporter-python>"
}
```

`source_root`는 이미 존재하는 로컬 디렉터리다. `sources`에는 고정 등록도 넣을 수 있다: `{"id":"<registered-id>","kind":"arm","label":"<display-label>","root":"<absolute-provider-directory>"}`. 같은 ID를 중복 등록하지 않는다.

녹화와 구성 편집은 학습용 Center나 learner Python 없이 사용할 수 있다. `export_python`은 변환할 때만 필요하므로 미준비 상태에서는 키를 생략한다. 변환기는 Linux에서 기존 절대 경로의 Python과 `lerobot==0.4.4`를 검사한다. 의존성을 자동 설치하지 않는다. `--omx-center-config`는 별도 학습 설정이며 녹화 설정을 대신하지 않는다.

## 로컬 생산자 등록

`source_root/<registered-id>/registration.json`에 `{"kind":"arm|camera","label":"<display-label>"}`을 둔다. `kind`는 실제로 `arm` 또는 `camera` 하나를 쓴다. 등록 ID는 1~64자의 영문·숫자·밑줄로 시작하고 이후 점·하이픈도 허용한다. 등록 디렉터리는 심볼릭 링크를 사용할 수 없다.

작업대는 목록 조회와 녹화 시작 때 이 등록부를 다시 읽는다. 장비 추가·제거에 소스 코드 수정은 필요 없다. 고정 `sources`나 등록부 경로를 바꾸려면 앱 실행 설정을 갱신한다. 고정 항목과 동적 항목의 합은 최대 96개다.

각 생산자 디렉터리의 파일 계약은 다음과 같다. 파일은 로컬 생산자가 쓰고 작업대가 읽는다.

| 파일 | 내용 |
|---|---|
| `descriptor.json` | 아래의 동결된 생산자 식별·단위·배치·시계 정보 |
| `events/<sequence>.json` | 순서 번호별 불변 관측 객체 |
| `latest.json` | 가장 최근 `events/<sequence>.json`과 같은 객체 |
| `events/<sequence>.jpg` | 카메라 관측의 RGB JPEG 원본 |
| `preview.jpg` | 선택적 미리보기. 이것만으로 녹화 가능한 생산자가 되지 않음 |

완성된 event와 JPEG를 먼저 게시하고 `latest.json`을 갱신한다. 번호는 0 이상의 증가하는 정수다. 작업대는 마지막 읽은 번호 이후의 event를 모두 읽으므로 아직 소비하지 않은 파일을 덮어쓰거나 지우지 않는다. 초기 연결은 최신 event에서 시작한다. 한 번에 따라잡을 수 있는 범위는 최대 256개이며 누락·역행·내용 불일치는 녹화를 무효화한다. 같은 JPEG라도 새 번호는 새 관측이다.

모든 descriptor에는 `kind`, `source_identity`, `session_epoch`, `clock_domain`, `rate_hz`가 필요하다. 같은 호스트의 `time.monotonic()` 초 단위를 쓴다. Linux의 도메인은 `host-monotonic:<현재 /proc/sys/kernel/random/boot_id 내용>`이다. 다른 호스트 시계나 wall-clock 시간을 섞지 않는다. producer 재시작에는 새 epoch를 부여한다.

팔 descriptor는 `owner_id`, `joint_names`, `state_units`, `action_units`, `calibration_revision`, `profile_revision`, `state_producer`, `reference_producer`, `reference_stage="post_guard_accepted"`도 선언한다. 팔 등록 ID는 저장 프로필의 arm ID와 일치해야 한다.

팔 event의 schema는 `rosy.passive-owner-sample/1`이다. descriptor의 `owner_id/source_identity/session_epoch/clock_domain/joint_names/state_units/action_units/calibration_revision/profile_revision/reference_stage`와 `sequence`, `state_timestamp`, `reference_timestamp`, `state`, `accepted_reference`, `reference_id`를 포함한다. 두 벡터는 선언된 전체 관절 순서의 유한값이다. **측정 상태 시각 ≤ guard 이후 수락 참조 시각 ≤ 작업대 수신 시각**이어야 한다. 요청 목표, 느린 legacy live 파일의 target, 위치만 있는 Fleet 관측은 수락 참조를 대신하지 않는다. 참조가 전송됐다는 사실과 실물 실행 성공은 구분한다.

카메라 descriptor에는 `shape=[3,height,width]`, `timestamp_semantics="host_receive"`도 둔다. event schema는 `rosy.passive-camera-sample/1`이며 `source_identity`, `session_epoch`, `clock_domain`, `shape`, `timestamp_semantics`, `sequence`, `timestamp`, `jpeg_sha256`를 포함한다. hash는 같은 번호 JPEG의 SHA256이다. 노출 시각을 측정한 동기화라고 표시하지 않는다. JSON은 파일당 64KiB, JPEG·미리보기는 16MiB 이하이며 링크를 거절한다.

## 구성 저장부터 학습까지

1. `/learning/record`에서 한 작업 팔 또는 두 작업 팔의 초안을 연다. 두 팔은 leader/follower 한 쌍을 뜻하지 않는다. 실제 관절·단위·장치 식별·카메라 크기를 입력하고 저장한다. 초안의 수용 상태는 미검증이다.
2. 카메라의 물리 식별과 역할을 확인한다. 손목 장착은 `wrist`로 적는다. 팔 ID에서 좌우를 추정하지 않는다. 과거 `front` 입력 키가 든 봉인 자료는 그대로 두고, 변경은 새 프로필 revision에 저장한다.
3. 저장 프로필과 프레임률·age/skew/gap 한계로 새 세션을 만든다. 생산자의 선언 rate가 녹화 FPS 이상이어야 한다. 표시되는 `ready` 뒤에도 시작 시 전체 프로필·생산자·시계를 다시 검사한다.
4. 녹화를 시작하고 완료 입력이 모이면 기록을 진행한다. 중지하면 마지막 완전한 grid까지의 draft가 남는다. 유지할 때 기본 결과는 `unknown`이다. `success/failure`는 별도로 귀속되는 사람의 명시적 판정이다. 버리기도 원본을 삭제하지 않는다.
5. 같은 동결 구성의 정상 시연을 두 개 이상 유지한 뒤 변환한다. 변환·ZIP 검증은 백그라운드에서 진행한다. 실패한 원본과 오류는 보존되며 새 요청으로 재시도한다.
6. 같은 프로젝트의 로컬 Center가 연결됐으면 학습 자료 전달을 선택한다. 전달 후 `/learning/imitate`에서 실제 검사·분할·ACT 학습을 진행한다. 자동 학습이나 HF 게시를 시작하지 않는다.

Fleet PC가 녹화 전용이면 ZIP을 내려받아 **먼저 압축을 푼다**. Learning PC의 `/learning/imitate`에서 그 표준 LeRobot 폴더를 선택해 기존 업로더로 전달한다. 원격 SSH 주소나 계정 캐시를 입력하지 않는다.

팔·관절 순서·단위·카메라 식별·배치 등의 프로필 내용을 바꾸면 새 revision으로 저장한다. 보정·생산자 epoch·프레임률을 포함한 동결 설정 변경은 새 세션/데이터셋 경계가 필요하다. 진행 중 구성을 바꾸지 않는다. 생산자 정보가 동결된 구성과 달라지거나 중간 grid가 빠지면 해당 시연은 무효다. 재시작 중이던 녹화도 자동으로 정상 봉인하지 않는다.

## 보관 범위와 한도

### 저장 회차 재생·검수

종료된 draft·kept 회차의 **저장 기록 재생·검수**에서 프레임별 원본 영상과 측정 관절값·수락 참조값을 함께 확인한다. 현재 장비가 연결되지 않아도 보유한 자료를 조회할 수 있다. 실제 팔을 움직이는 재생은 아니다.

이전·다음·프레임 선택·재생/일시정지로 이동하며 값의 원래 단위와 상대 시각을 표시한다. 상세 시각은 원본 기록을 유지한다. 정책 카메라뿐 아니라 보관된 검수용 카메라도 표시하며, 실시간 미리보기로 지난 영상을 대신하지 않는다. 화면을 열거나 재생한 것만으로 작업 성공·사람 검수 완료·보관을 기록하지 않는다.

자료 준비는 백그라운드에서 한 회차씩 수행한다. 준비 중 새 녹화는 제한하고 정지·상태 조회는 계속 응답한다. 닫으면 준비를 취소하거나 파생 인덱스를 해제한다. 무결성 확인은 로딩 당시의 내용 검증이며 실물 안전·성공 수용은 아니다. 프레임 조회 때 원본 메타데이터, 영상 조회 때 선택 JPEG를 다시 확인한다.

카메라 목적은 `policy/record/reward/evaluation/monitor`다. 선택된 policy·record·reward·evaluation 영상은 raw 봉인 자료에 남으며 모두 녹화 무결성에 필요하다. monitor-only는 미리보기만 한다. 학습용 LeRobot 폴더에는 **policy 영상만** 넣는다. 다른 검수 영상은 raw 자료에 남고 ZIP에는 들어가지 않는다. 봉인은 내용 무결성이며 native 안전 수용·물리 학습 검증·정책 활성화를 뜻하지 않는다.

현재 웹 녹화 FPS는 1~60 정수, 각 timing 한계는 0보다 크고 2초 이하다. 실제 rate·시계·관측 품질에 맞춰 명시적으로 정하며 자동 FPS 변경은 없다. ACT 입력은 policy 영상 최대 8개, 전체 action 최대 64차원이다. raw 영상 합계는 grid당 16M pixels 이하, 시연당 최대 200,000프레임·2GiB다. 변환은 2~1,000개 시연과 합계 200,000프레임 이하를 받는다. 변환 자료·ZIP은 각각 2GiB 이하이며 파일당 512MiB·최대 10,000개 파일 제한도 적용한다.

저장 위치는 `<review-state>/recordings/`다. 원본·SQLite·봉인 자료를 함께 보존한다. JPEG 작업과 파일 쓰기는 actuator callback 안에서 수행하지 않는다. 설치된 native 생산자 hook, 보정 및 실물 조작 수용은 별도 확인이 필요하다.

## HTTP 계약

접두사는 `/api/learning/recording`이다. 협업 계정 사용 시 GET은 해당 프로젝트 view, POST는 manage 권한이 필요하다. 쓰기는 기존 origin·CSRF 검사와 `X-Pinky-Token`을 쓰며 actor는 서버의 인증 세션에서 얻는다. 계정 없는 로컬 모드는 사람 신원을 증명하지 않는다. 요청 UUID를 보존해 재시도하며 다른 내용·actor로 재사용하지 않는다.

| 메서드·경로 | 요청 또는 응답 |
|---|---|
| GET `/snapshot` | 호스트, 프로필, 소스 준비 상태, 세션, 변환기·로컬 전달 가용성 |
| GET `/profiles`, `/profile/<uuid>` | 전체 Profiles record 목록 또는 단일 record |
| POST `/profile` | `profile,request_id,parent_id?` |
| POST `/session` | `request_id,name,profile_id,profile_revision,timing` |
| GET `/session/<uuid>` | 동결 구성 버전·시연·변환·전달 상태 |
| GET `/review/<session>/<episode>` | 준비·완료·실패 상태와 동결 구성·무결성 조회 근거; 명시적 열기/재시도에만 `?refresh=1` |
| GET `/review-frame/<session>/<episode>/<evidence_revision>/<index>` | 원본 state/action·팔별 값과 단위·시각·저장 영상 URL |
| GET `/review-image/<session>/<episode>/<evidence_revision>/<index>/<camera>` | 검증된 원본 JPEG; 현재 live 미리보기와 구분 |
| POST `/review-close` | `session_id,episode_id`; 파생 검수 준비 취소·인덱스 해제, 원본·판정 불변 |
| POST `/start`, `/stop` | `session_id,request_id` |
| POST `/keep` | `session_id,episode_id,request_id,task_outcome` |
| POST `/discard` | `session_id,episode_id,request_id` |
| POST `/export` | `session_id,request_id`; 비동기 로컬 변환 |
| GET `/artifact/<uuid>` | 검증된 policy-only LeRobot ZIP 스트림 |
| POST `/publish` | `session_id,request_id`; 같은 프로젝트의 로컬 Studies에 전달, `study_id,url` 반환 |

`publish`는 HF 게시가 아니다. 브라우저가 원본 경로·명령·자격 증명을 지정할 수 없다. 소스 미리보기는 GET `/preview/<registered-id>`이며 녹화 가용성과 별개다.
