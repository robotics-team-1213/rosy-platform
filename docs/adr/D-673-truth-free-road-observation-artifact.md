## D-673 정답 없는 도로 관측을 고정 파일로 산출하고 hash로 다시 읽는다

**Status:** Accepted (2026-10-12, D-659 파이프라인의 내부 진단 전달). 외부 API·ROS topic·운영 consumer·장치 전송/활성화 계약이 아니다.

### Context

D-670 관측 함수는 numpy 결과를 반환하지만 호출 입력의 파일 계보와 저장 결과 readback은 없다. 기존 shadow/paint 전달은 전체 도로면을 거절하며 그 경계를 유지해야 한다. 독립 정답과 무관하게 같은 모델·입력을 실행하는 파일 진단 경로를 먼저 연결한다.

### Decision

1. `rosy_ml observe MODEL --inputs DIR --max-age-ns N --out FILE`은 로봇 설정 없이 실행한다. evaluation 소유의 `road_observation_replay`가 D-670 함수를 호출한다. 새 서비스·장치 pointer·명령 publisher를 추가하지 않는다.
2. 입력 DIR은 기존 `store.read_fixed_manifest`의 content-addressed 불변 폴더다. manifest schema는 `rosy.perception.road-observation-input/1`이며 필드는 schema, model_manifest_sha256, image, image_sha256, image_snapshot, anchor_snapshot, seed_pixels, now_ns다. 정답·목적지·통행 정책 필드를 받지 않는다. image는 폴더 안 상대 경로이며 hash와 uint8 BGR decode를 검증한다. snapshot은 D-667 형식이고 기준점은 원본 영상 grid다. model manifest hash가 실제 로드 파일과 달라지면 추론 전에 거절한다.
3. 보고 schema는 `rosy.perception.road-observation-artifact/1`이다. 입력 content SHA·영상 SHA·model manifest SHA와 classes, 원본 snapshot/기준점/평가 시각, D-670 모델 revision·camera profile·전처리·ROI·numpy 결과를 JSON으로 남긴다. 추론 전후 모델 파일·manifest·입력 content를 재검증한다. 원본과 예측 grid는 각각 최대 1,000,000화소로 제한하며 readback 파일은 최대 64 MiB다. 이 제한은 파일 진단 경로에만 적용한다.
4. 출력은 기존 파일/링크를 덮지 않고 exclusive create한다. `read_artifact(FILE, SHA256)`는 정확한 파일 hash와 schema/HOLD, mask shape·binary 형식·도로면 class labels 대응을 검증한다. 실행 성공 전 작성 파일을 같은 hash로 다시 읽는다. hash는 byte identity이며 signer·독립 검수·물리 보정 또는 인지 승인이 아니다.
5. 명령은 성공해도 항상 HOLD다. image 무효는 결과 없음, anchor 무효는 구역 없음이라는 D-670 동작을 보존한다. replay now_ns로 계산한 나이와 infer latency는 현재 장치 clock alignment·촬영부터 전달까지 지연·프레임 손실의 증거가 아니다. 실제 전송·장치 consumer/readback과 독립 인지 수용은 후속 단계다.

### Verification

합성 모델/영상으로 정답 없이 실행·mask/계보 roundtrip, model/image/input mutation 및 hash/shape/의미 오류 거절, crop와 image/anchor 보류, 출력 덮어쓰기 거절을 확인한다. CLI는 로봇 설정을 읽기 전에 dispatch한다. source 시험과 파일 readback은 실제 장치 전달이나 실물/시뮬레이션 인지 성능을 증명하지 않는다.

**Related:** D-659, D-663, D-666, D-667, D-670.

Readback은 중복된 영상/model manifest hash와 snapshot ID의 일치 및 입력 오류 시 구역 보류도 확인한다. 예측 grid 제한은 session 생성·warm-up 전에 manifest에서 검사한다. 영상 경로는 기존 `review_evidence.safe_file`의 플랫폼 공통 상대 파일 규칙을 따른다.
