# 객체 라벨과 원본 이미지 bytes의 export binding

2026-10-04, 기준 checkout `3cca94fca`. Developer-side object_boxes CLI만 변경했다.
기존 전체 프레임 검수 경계는 [이전 기록](object-review-export-2026-10-04.md)을 유지한다.

## 문제와 새 입력 계약

index가 같아도 원본 이미지가 바뀌면 이전 라벨은 그 이미지의 정답이 아니다.
이전 exporter는 승인/완료 상태만 확인하고 실제 이미지나 hash를 검사하지 않았다.
이미지 교체, review/source hash 불일치, 이미지 루트 밖 경로, 크기 불일치,
binding 없는 승인 행을 RED6로 재현했다.

승인된 프레임의 source row에는 index/objects 외에 아래 필드를 요구한다.

```json
{"index": 0, "image": "frames/000000.png", "image_sha256": "<actual-image-sha256>", "objects": []}
```

human row에도 같은 image_sha256을 넣는다. approved/complete bool true/명시 boxes라는
기존 조건을 충족한 뒤, 두 hash와 실제 이미지 bytes의 hash를 모두 비교한다.
이미지는 source JSONL 폴더 또는 명시한 `--images <root>` 아래의 상대 경로여야 한다.
경로 resolve 후 루트 이탈을 거절하며 JPEG/PNG를 실제 decode해 `--size W H`와 비교한다.
hash만 선언하고 실제 파일을 확인하지 않는 경로는 없다.

기존 autolabel index만으로 사진을 추정하지 않는다. curator가 해당 프레임의 상대 image
경로와 실제 hash를 source row에 연결해야 승인 라벨을 export할 수 있다.
pending/partial 행은 이 단계에서 승인으로 추정하지 않고 그대로 대기열에 남긴다.

## 산출물 보존

검증은 출력 폴더 생성 전에 완료한다. 새 출력에는 다음을 보존한다.

- YOLO txt와 검증할 때 읽은 이미지 bytes의 snapshot (`images/<index>.<ext>`).
- 실제로 파싱한 source.jsonl/human.jsonl bytes와 pending review_queue.
- manifest.json: class order, size, exported/queued indices, 위 모든 파일의 상대 경로/hash/bytes.

이미지를 다시 읽어 복사하지 않으므로 검증 후 원본 파일 변경은 snapshot에 영향을 주지 않는다.
새 경로만 허용하지만 파일 시스템을 write-protect한 것은 아니다. 이후 소비자는 manifest hash를
검증해야 한다. manifest의 reviewer_authentication은 unverified이며 이미지 integrity가
사람 인증·독립 과제 평가·운영 승격 권한을 주지 않는다.

## 실제 검토 묶음 readback과 검증

`X:/DevTemp/rosy-learning-audit-20261004/object-review-image-binding-v1`에서
기존 4프레임/7박스의 video/frame/hash를 원본 object image 경로에 연결했다.
실제 4 image SHA를 확인했고 human bytes는 기존과 같다.
결과 **txt0 / pending4**, manifest의 3 파일 ref 모두 bytes/hash가 일치했다.
승인된 실제 이미지 export는 없으며 positive snapshot 증거는 unit fixture에 한정된다.
source SHA-256: `d0f58826498e2394a2fed9bd948d494946c740067ad26bf2ef5b9c125178b8bf`.

object39pass / object-autolabel-review71pass. Positive fixture는 원본 이미지 변경 후에도
snapshot hash가 같고 manifest 파일 목록이 빠짐없이 일치함을 검사한다.
독립 검토39pass와 실제 3 ref 전체 coverage/hash, 원본 4 image SHA, frozen source 일치를 확인했다.
object CLI UTF8 검사1pass/11deselected, 문서15pass/1Windows-bashskip,
변경 파일 secrets scanner 새 검출0이다. 기존 전체 secrets guard 실패는 유지한다.
사람 검수, recording/group provenance 보강, 클래스·신호 상태별 독립 평가 coverage,
훈련용 immutable dataset build와 새 모델 학습, 모델 PC/로봇 shadow/rollback은 남아 있다.
기존 secrets guard 실패와 DEVICE/FIELD 수용도 이 작업으로 해결되지 않았다.
