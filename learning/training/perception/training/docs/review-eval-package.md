# 고정 평가 원본 근거 패키지

`review_eval_package.py`는 D-379 평가 버전과 동결된 원본 근거를 기존
`rosy.pinky-fixed-eval-companion/1` 형식으로 묶는 개발자용 도구다.
[D-464](../../../../../docs/adr/D-464-pinky-indexed-review-dataset-build.md)의
소비자 `review_eval_companion.py`로 발행 전 바이트를 검증한다. 평가 버전,
라벨, 사람 승인, 학습 요청과 모델 상태는 변경하지 않는다.

## 필요한 입력

평가 폴더는 내용 해시로 식별되는 완전한 D-379 `purpose=eval` 버전이어야
한다. `manifest.json`과 모든 이미지·마스크·confidence 파일이 필요하다.
세션마다 원본 labels JSONL, meta JSON, 영상, sidecar JSONL, 전체 ordinal/PTS
JSON 및 선택된 각 평가 행의 원본 extraction 이미지·마스크·confidence가
필요하다. 모든 원본 경로는 절대 경로이고 각 파일의 실제 raw SHA256을
명시해야 한다. 링크·junction·경로 순회와 바뀐 입력은 거부한다.

`--sources`는 다음 구조의 JSON 배열이다. 생략 부호 대신 실제 전체 세션과
모든 평가 이미지 행을 넣는다. `sha256`에는 소문자 64자리 원본 바이트
해시를 넣는다.

```json
[
  {
    "session": "session-id",
    "labels": {"path": "X:/DevTemp/frozen/labels.jsonl", "sha256": "RAW_SHA256"},
    "meta": {"path": "X:/DevTemp/frozen/meta.json", "sha256": "RAW_SHA256"},
    "video": {"path": "X:/DevTemp/frozen/video.mp4", "sha256": "RAW_SHA256"},
    "sidecar": {"path": "X:/DevTemp/frozen/sidecar.jsonl", "sha256": "RAW_SHA256"},
    "pts": {"path": "X:/DevTemp/frozen/pts.json", "sha256": "RAW_SHA256"},
    "extractions": {
      "images/session-id/session-id__000001.jpg": {
        "image": {"path": "X:/DevTemp/frozen/extracted.jpg", "sha256": "RAW_SHA256"},
        "mask": {"path": "X:/DevTemp/frozen/mask.png", "sha256": "RAW_SHA256"},
        "conf": {"path": "X:/DevTemp/frozen/conf.png", "sha256": "RAW_SHA256"}
      }
    }
  }
]
```

PTS는 caller가 동결해 해시를 고정한 전체 프레임 배열이다. 각 항목은
`{"video_frame": 0, "pts": 123, "time_base": "1/90000"}` 형태이며
`video_frame`은 0부터 연속이어야 한다. 이 도구는 ffprobe를 실행하거나
PTS의 측정 사실을 새로 인증하지 않는다.

## 실행

저장소 루트에서 실행한다. 출력은 아직 존재하지 않는 폴더를 지정한다.
Windows 출력과 임시 staging은 `X:/DevTemp` 아래에만 생성한다.

```powershell
python learning/training/perception/training/review_eval_package.py `
  --eval-folder X:/DevTemp/frozen-eval/CONTENT_SHA256 `
  --sources X:/DevTemp/frozen/sources.json `
  --out X:/DevTemp/eval-companion-new
```

라이브러리는 `package_eval_companion(eval_folder, source_records, output)`이다.
성공하면 출력 경로, companion manifest 해시, 평가 ref와 행 수를 반환한다.
CLI 입력 오류는 `status=HOLD`, exit 2를 반환한다.

## 보장과 한계

모든 입력 검증은 staging 생성 전에 수행한다. 전체 labels 행의 canonical
digest를 평가 manifest와 대조하고 D-379 이미지·마스크·confidence 이름의
선택 인덱스를 해당 labels 행에 연결한다. 원본 영상 ordinal은 labels의
`t`와 sidecar의 유일한 정확 일치로만 구한다. 선택 인덱스를 영상 프레임
번호로 사용하거나 가까운 timestamp, FPS, JPEG 허용 오차를 추정하지 않는다.
추출 파일은 평가 파일과 원본 바이트가 같아야 한다.

동결한 바이트를 staging에 복사한 뒤 기존 소비자로 다시 검증하고 입력을
재확인한다. 출력 폴더는 독점 생성하며 기존 폴더를 덮어쓰지 않는다.
`COMPLETE`는 최종 출력에서 마지막으로 기록한다. 늦은 오류는 미봉인
폴더를 남길 수 있다. 파일이 없어졌거나 되돌려졌다고 주장하지 않는다.

결과의 `capture_group`과 `group_basis`는 null이며 decoded video pixel,
operator collection 검증, `training_dataset_qualified`, `training_admission`은
항상 false다. 원본 영상 바이트·PTS 근거와 JPEG extraction 바이트 일치는
영상 디코딩 픽셀 일치나 사람이 검수한 정답을 의미하지 않는다. 실제 고정
평가 자료의 기존 JPEG/원본 픽셀 및 collection 경계 HOLD를 해제하지 않는다.
회수한 labels/meta 네 파일만으로는 패키지를 만들 수 없다. 모든 평가 파일,
원본 영상·sidecar·PTS와 각 extraction 세 파일을 추가로 확보해야 한다.

입력을 읽는 동안의 변경은 안정적 바이트 읽기와 발행 전 재검사로 탐지한다.
검사 사이에 바뀌었다가 원래 바이트로 복귀한 경로의 모든 이력을 증명하지는
않는다. 실제 패키지는 검사한 동결 스냅샷 바이트로 구성된다.
