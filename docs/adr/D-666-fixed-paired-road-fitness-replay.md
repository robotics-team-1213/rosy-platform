## D-666 고정 도로면/현재 구역 정답과 관측 입력의 독립 재생 실행 계약

**Status:** Accepted (2026-10-11, D-659 실행과 사용자 인지/주행 단계 분리 지시). 내부 오프라인 진단 계약이며 인지 적합성·장치 수용·주행 활성화 승인이 아니다.

### Context

D-663은 모델 drivable 의미를 도로면으로 구별하고 D-665는 현재 구역을 관측 로직으로 산출한다. 프레임 평가와 모델 resize/crop 정합·도메인별 집계는 구현했지만 고정 파일/정답을 읽는 실행 경로가 필요하다. Desktop 20261010 v13 검수본은 기존 로봇 연결 구역 의미와 manifest 파일 hash를 사용한다. 이를 전체 도로면 정답 또는 store content SHA로 자동 바꾸지 않는다.

### Decision

#### 1. 기존 immutable store와 검수 출판물을 사용한다

도로면과 현재 구역 정답은 기존 `rosy.perception.dataset/1`, `purpose: eval`의 서로 다른 고정 eval set이다. drivable semantic은 각각 `road_surface/1`, `current_road_region/1`이다. `pixel-classes.yaml`, `authority.json`, frames의 image/mask hash·identity·session·capture_group·approval hash를 기존 검수 authority 규칙으로 확인한다. 클래스 서명·마스크 버전·승인 화소 범위·원본 이미지와 실제 mask가 결속되어야 한다. class mask는 자기 drivable index=1, 다른 알려진 class=0, 원본 255=255의 이진 평가 정답으로 변환한다. 정답은 모델 입력과 분리한다.

두 eval set의 frame identity 집합과 각 image hash·원본 세션·capture group이 같아야 한다. 모든 frame은 eval split이고 source/capture group은 기존 store 예약에 결속한다. 선언한 학습 dataset들과 세션/capture group/image hash가 겹치면 실행을 거절한다. 학습과 도로면 모델의 클래스 의미도 비교한다. 원본 영상 단위 lineage와 upstream pretraining을 확인하지 않은 결과를 완전 독립으로 선언하지 않는다.

#### 2. 관측 입력을 정답과 별도로 고정한다

입력 묶음은 content SHA 이름의 immutable 디렉터리와 `manifest.json`이다. 내부 schema는 `rosy.perception.region-inputs/1`이며 아래 필드를 가진다.

| 필드 | 의미 |
|---|---|
| `model_revision` | 고정 후보 revision |
| `road_eval_sha256`, `region_eval_sha256` | 두 eval set의 전체 store content SHA |
| `preprocessing_sha256` | 기존 model manifest `input`을 `review_evidence.encoded`로 인코딩한 SHA256 |
| `training_refs` | 기존 `name@content_sha` dataset 참조 목록; 후보의 직접 학습 버전을 포함 |
| `frames` | 아래 관측 입력 목록; eval identity 집합과 정확히 일치 |

각 frame은 `identity`, `image_sha256`, `domain`(`real`/`simulation`), `conditions`(이름 목록), `now_ns`, `image_snapshot`, `anchor_snapshot`, `seed_pixels`를 가진다. snapshot은 기존 World ObservationSnapshot의 필드만 사용한다. received_at은 timezone 포함 ISO8601, validity는 기존 enum 문자열, evidence_refs는 JSON 목록이다. seed_pixels는 원본 카메라 grid의 정수 `[row, col]` 목록이다. 시간·위치·보정·transform·reference 유효성 및 resize/crop은 D-665와 기존 프레임 어댑터가 처리한다. simulator 정답 pose/ID나 정답 mask에서 기준점을 만들지 않는다.

content 검증은 안정적인 manifest bytes와 디렉터리 전체 hash를 결속하고 symlink 파일을 거절한다. 실행 전후 dataset/입력 content와 모델 manifest/모델 파일을 확인한다. 실행 중 파일 변경은 오류이며 정상 보고서를 출판하지 않는다.

#### 3. 실행과 보고는 승인/전달 경로와 분리한다

기존 `rosy_ml`에 `fitness MODEL --store STORE --road-eval DIR --region-eval DIR --inputs DIR --max-age-ns N --out FILE`을 추가한다. explicit 오프라인 경로를 사용하므로 로봇 접속 설정은 요구하지 않는다. 기존 intake/deliver/promote/watch를 실행하지 않고 pointer나 장치 설정을 쓰지 않는다.

보고는 고정 후보·입력·eval·학습 참조, 검수 저장본의 digest, 프레임별 결과와 별도 실물/시뮬레이션·조건별 지표/분모/보류/ROI coverage를 담는다. 이미 존재하는 out 파일은 덮어쓰지 않는다. 성공 exit 0은 **진단 실행 완료**이며 fitness verdict는 항상 HOLD다. 설정/형식/결속 오류는 exit 2이며 정상 보고서를 쓰지 않는다. 출력물은 공개 source 밖의 승인된 artifact/scratch 위치에 둔다.

저장된 authority의 구조·승인 결속은 live 검수 freshness, 검수자 독립성, 실제 보정·기준점 provenance, upstream 학습 closure를 증명하지 않는다. 이 미확인 항목과 실제/시뮬레이션 독립 성능·물체·사전 고정 임계값·장치 버전/지연/손실 증거를 별도 수용 단계에서 확인한다. report나 CLI 실행으로 이 증거를 대체하지 않는다.

### Consequences and verification

기존 store·World API·검수 authority·model loader/preprocess·road_fitness를 재사용한다. 새 segmentation head·role·운영 consumer·command writer·서비스는 추가하지 않는다. legacy/자동 eval set에는 이름만으로 새 의미와 사람 승인을 부여하지 않는다.

시험은 두 정답 identity/hash 불일치, 승인/클래스/마스크 불일치, 예약/학습 중복, 관측 묶음의 고정 버전·전처리 불일치, 실행 중 변경, out 덮어쓰기 거절, crop/미관측/보류 분모와 로봇 설정 없는 CLI를 검증한다. 실제 독립 데이터 실행·장치 전달·현장 수용은 별도 증거다.

**Related:** [D-659](D-659-perception-fitness-and-road-region-semantics.md), [D-663](D-663-versioned-road-label-semantics.md), [D-665](D-665-observed-road-region-and-paired-fitness.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md).
