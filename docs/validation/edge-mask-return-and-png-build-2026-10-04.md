# 사람 검수 마스크 반환과 원본 PNG dataset 입력

2026-10-04, 앞 단계는 [edge candidate intake](edge-candidate-review-intake-2026-10-04.md)다.
`learning/training/perception/dataset/edge_review_return.py`를 추가하고 기존
`build.py`의 explicit image 경로/해시 입력을 연결했다. JPEG legacy 입력은 유지한다.

## 연결한 동작

반환 도구는 원본 pack COMPLETE/receipt와 모든 참조 파일을 캡처해 검증한다.
사람 반환 JSONL은 candidate index와 원본 image SHA256, CVAT mask 경로/SHA256을
묶어야 한다. `review_status=approved`, `complete_frame_review=true`,
`background_reviewed=true`가 모두 필요하다. 마지막 항목은 CVAT의 기본 배경색까지
화면 전체에서 사람이 확인했다는 명시적 선언이다. 미칠한 픽셀을 자동 정답으로
인정하지 않으며 부분 검수는 이번 반환 경로에서 승인하지 않는다.

CVAT mask 이름은 `SESSION__ORIGINAL_FRAME_INDEX.png`다. 원본 해상도와 색상→클래스
매핑을 검증하고, 기존 고정 평가셋의 전체 content hash와 세션을 확인한다.
원래 pack에 기록된 모든 eval manifest 버전을 다시 제공해야 한다.
source image bytes, mask bytes, classes, labelmap을 한 번 캡처한 값으로 출력한다.
평가셋도 전체 content 검증에 사용한 동일 manifest bytes로 버전의 출처를 대조한다.

승인된 프레임만 `frames/<session>/frames.jsonl`과 원본 PNG, CVAT mask 입력으로
내보낸다. 기존 builder는 image 경로와 hash를 읽고 원본 PNG의 확장자·bytes를
보존한다. human 입력에서는 승인 선언과 파생 바인딩의 일치, mask/labelmap hash와
classes signature도 dataset 생성 전에 다시 검증한다. human metadata가 빠지거나
상충하면 거절한다. 미승인 입력은 `queued.jsonl`에 남는다.

반환 작업은 dataset qualification이나 model READY가 아니다. dataset 구축에는
최소 두 원본 세션과 실제 mask 승인, 고정 평가셋 제외가 필요하다. 기존 dataset을
합칠 경우 canonical train/val 세션 배치를 별도로 확인해야 한다. 새 현장 heldout,
학습·intake·shadow 전달/rollback과 운영 수용은 이 단계의 완료로 간주하지 않는다.

## 확인한 증거와 한계

- Root 관련 73 passed, 1 skipped. 독립 수신기/builder/evalset 64 passed, 1 skipped.
- 문서 placement/layout까지 포함한 최종 검증은 88 passed, 2 skipped다.
- 합성 두 세션으로 CVAT 승인 반환→기존 builder→PNG bytes 보존→train/val 세션
  분리→고정 평가셋 disjoint reference의 양성 경로를 확인했다. 실제 사람 정답이 아니다.
- 승인 후 mask 변경, 평가 manifest의 검증/재읽기 교체, session metadata 누락의
  독립 재현을 거쳐 모두 거절하도록 수정했다. 이미지 해시/경로, 원본과 mask 크기,
  클래스/labelmap 변경과 승인값 상충도 관련 guard로 거절한다.
- 모델 PC의 실제279 후보에 **자동 생성 pending template**를 넣은 반환 실행 exit0:
  exported0/queued279/training qualified false, PNG/mask/frames.jsonl 생성 없음.
  template는 사람 반환이나 승인 기록이 아니다. 기존 고정 eval version을 재검증했다.
- 실제 실행 입력/결과와 소스별 SHA256은
  X:/DevTemp/rosy-learning-audit-20261004/edge-mask-return-evidence-v2에 있다.
  반환 receipt의 5개 참조와 COMPLETE를 확인했다.
  로컬로 받은 결과도 root에서 전 참조 hash/크기와 COMPLETE를 검증했고, 실제 실행
  도구 3개의 SHA256이 현 소스와 일치한다. `local-verification.json`에 기록했다.

횡단보도·정지선의 실제 사람이 검수한 mask는 아직 없다. 회전교차로 상태/진입 판단은
새로운 별도 검증 과제이며 이 segmentation 반환으로 증명하지 않는다. 어두운 장면
개선은 이전 사용자 결정대로 후속 ADR 범위다. 기존 class index/role과 평가 수치 게이트,
배포 권한 및 로봇 제어 경계를 변경하지 않았다.
