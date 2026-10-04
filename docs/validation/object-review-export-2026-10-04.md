# 객체 초안과 전체 프레임 검수의 학습 export 경계

2026-10-04, 기준 checkout `fc0478050`에서 developer-side object_boxes CLI를 수정했다.
ROS/owner/운영 설정을 변경한 작업은 아니다.

## 발견한 공백

기존 CLI는 human JSONL에 index 행이 있으면 검수 완료로 취급했다.
pending/partial 행도 박스 파일을 만들고 빈 boxes 또는 누락된 boxes는
검수된 음성 샘플로 해석할 수 있었다. 기존 출력 폴더를 재사용하면 새 실행에서
대기열로 돌아간 프레임의 과거 txt가 남아 학습 입력에 섞일 수도 있었다.
10개 pending/partial/불명확 완료 테스트와 기존 출력 재사용 테스트, 총 11개 RED로 재현했다.

## 새 export 계약

human row는 다음 필드를 모두 갖춰야 한다.

```json
{"index": 0, "review_status": "approved", "complete_frame_review": true,
 "boxes": [{"bbox_xyxy": [100, 100, 140, 160], "label": "robot"}]}
```

- 정확한 approved 상태와 bool true인 전체 프레임 검수만 export 대상이다.
- 명시적인 boxes 배열을 요구한다. 승인된 전체 프레임의 빈 배열만 음성 샘플이다.
- 남은 unlabelled LiDAR 후보가 있으면 기존처럼 대기열에 남긴다.
- 기존 형식처럼 index/boxes만 있는 행, assistant pending 초안은 승인으로 추정하지 않는다.
  review_queue에는 원래 review 행과 사유를 보존한다.
- 양쪽 index는 중복 없는 nonnegative integer이며 bool은 거절한다.
  source에 없는 human index와 이미지 밖 approved 박스를 거절한다.
  none/reject 박스도 merge 전에 검사해 잘못된 reject가 음성 샘플을 만들지 못하게 한다.
- 검증을 먼저 완료한 뒤 새 출력 폴더만 생성한다. 기존 폴더는 덮어쓰거나 재사용하지 않는다.

CLI: `python learning/training/perception/dataset/object_boxes.py <labels.jsonl>`
`--human <human.jsonl> --out <new-directory-on-X> --size 320 240`.
이 플래그들은 annotation 완료 상태를 명시한다. reviewer 인증 또는 image SHA binding은 아니다.

## 실제 영상 초안 readback

`X:/DevTemp/rosy-learning-audit-20261004/object-review-export-v1`과 최종 v2에 실제 검토 묶음의
4프레임/7박스를 적용했다. original video/frame/image SHA를 보존하고 이 작은 입력 묶음에서
index를 순서대로 부여했다. LiDAR 후보는 없으며 카메라 timestamp를 합성하지 않았다.
원래 4 이미지 SHA를 확인했고 결과는 **training txt 0 / pending queue 4**였다.
원본 초안과 사람 검수 상태는 수정하지 않았다.
최종 source SHA-256: `84ca6a0642b79eb876f77e8112d89e25f1b5b41fda9ea13f9018528df83c8fa1`.
v2의 입력 bytes는 v1과 같고 결과도 txt0/queue4이다. v2에 최종 source bytes를 보존했다.

## 검증과 남은 작업

독립 검토가 이미지 밖 none reject가 merge에서 제거되어 경계 검사를 우회하는 문제를 발견했다.
추가 RED1로 재현한 뒤 merge 이전 모든 approved human box 검사로 수정했다.
최종 object suite 33 pass, object/autolabel/review 회귀 65 pass.
독립 최종 검토도 33 pass와 none 경계 우회 차단, v2 입력/source bytes 및 4 image SHA를 확인했다.
초기 object+CLI 38 pass에는 unrelated lane_replay CLI의 cp949 thread decoding warning이 있었다.
수정 object CLI 자체는 PYTHONUTF8=1로 help를 확인했다.
문서 검사 15 pass / 1 Windows-bash skip. 기존 secrets guard 실패는 이 작업으로 해결되지 않았다.

실제 사람이 검수 완료한 데이터는 아직 없고 새 객체 모델도 학습하지 않았다.
라벨과 원본 이미지의 binding, 독립 클래스/신호 상태 coverage, immutable dataset export,
객체/신호 학습 및 정확도·장치 지연 평가가 남아 있다. 기존 고정 평가 세트는 유지한다.
신호 상태나 person_feet를 기존 OBJECT_CLASSES에 임의 remap하지 않는다.
