# 과거 영상 edge 후보의 출처 검증과 사람 검수 대기열

2026-10-04. 사용자가 선택한 `training-edgecase-handoff.md`를 현재 학습 루프의
추가 자료로 읽고, `learning/training/perception/dataset/edge_review.py`를 추가했다.
모델 PC에서 원본 manifest, 279 PNG 파일/decoded BGR 해시, 6 원본 영상과 기록된
sidecar 해시를 다시 확인한 뒤 새 검수 묶음을 생성했다. 원본을 수정하지 않는다.

- 기존 store의 학습 데이터셋 manifest 4개를 snapshot으로 대조했다.
  183 후보는 이미 사용된 원본 세션, 96 후보는 이 비교 목록에서 세션을 찾지 못했다.
  이는 세션 기준 membership이며 동일 픽셀 중복이나 모든 과거 실험의 완전한 감사가 아니다.
- 고정 평가셋 manifest의 세션과 중복된 후보는 0이다. 별도 기존 `read_eval_set`
  검증에서도 `pinky-heldout-20261001` 버전 `0260507375e43354aadbdded329c8b5bd21e12fcbd3c4035e97ee3745b389094`
  전체 content hash와 두 세션을 재확인했다. 범용 queue CLI 자체는 비교 manifest
  snapshot에 기반하며 그 데이터셋 전체 파일의 무결성을 인증하지 않는다.
- 전체 279 후보는 `unlabelled/pending_human`, 승인 0, training qualified false다.
  모든 후보의 `eligible_new_holdout`은 false다. 별도 새 현장 세션이 필요하다.
  평가 세션과 중복되는 입력은 `quarantine_eval_overlap`으로 표시한다.
- 자동 dark/blur/clipping 태그는 검수 힌트다. 어두운 장면 개선은 이전 사용자 결정대로
  후속 ADR 범위이며 데이터를 삭제하거나 기존 평가 기준을 약화하지 않는다.

묶음에는 원본 PNG 그대로의 CVAT image ZIP, 브라우저 gallery, provenance JSONL,
비교 manifest snapshot, 파일 hash/크기 receipt와 마지막 COMPLETE가 있다.
영상 시간은 video-relative이며 인증된 capture stamp가 아니다. PNG와 원본 video의
기록 해시는 확인했지만 모든 후보의 원본 프레임을 다시 decode해 대조한 것은 아니다.
과거 영상의 새로운 선별이고 새 live capture가 아니다. 48장/영상 선별 상한과
후반 구간 누락 가능성도 원본 source manifest에 보존한다.

독립 라벨 검토에서 실제 279 queue rows, 고유 image와 `(session, frame)` 279개,
CVAT ZIP 279개 고유 entry와 전 PNG byte hash/CRC를 확인했다. 범용 입력의
CVAT 이름 충돌은 실패 테스트로 재현 후 출력 생성 전에 거절하도록 고쳤다.
경로 이탈, 파일/decoded 해시 변경, 원본 영상 변경, 누락된 source를 거절한다.

실제 최종 묶음: X:/DevTemp/rosy-learning-audit-20261004/edge-review-v2.
원본 manifest SHA256: `2ac68b18699428617197b7232aca517b696bad1885e5e42924e503cc3bc14db0`.
raw 이미지와 private machine 경로는 공개 저장소에 넣지 않는다.

로컬 tar 전송이 종료된 뒤 receipt 288개 참조의 hash/크기, COMPLETE, 279 decoded
PNG hash와 ZIP CRC/고유 이름을 root에서 다시 확인했다. 근거는 해당 임시 폴더 옆
`edge-review-v2-local-validation.json`이다. 관련 검수 도구와 문서 placement/layout
검증은 41 passed, 1 skipped다. 전체 CI나 DEVICE/FIELD 수용 결과가 아니다.
일부 과거 데이터셋에서는 같은 세션의 train/val 배치가 서로 다르므로 다음 dataset
구축 때 canonical split을 명시해야 한다. 이 queue는 split을 새로 배정하지 않는다.

사용자는 CVAT에서 횡단보도 줄무늬/차선, 벽 경계, 원형 경계/가림을 검수한다.
원형 경계 라벨은 회전교차로 진입/진출 판단의 증거가 아니다. 현재 6개 segmentation
클래스에 roundabout 상태를 임의 추가하지 않는다. 횡단보도·정지선의 기존 정답 픽셀
부족은 이 묶음 생성만으로 해결되지 않는다.

이 image ZIP은 기존 `build.py --frames`에 직접 들어가는 완성 dataset이 아니다.
현재 reader는 JPEG와 frames.jsonl을 요구한다. CVAT mask 반환의 원본 PNG 바인딩,
사람 승인, 클래스/255 미라벨 픽셀과 세션 분리 검증은 다음 단계다. 학습·모델 승격,
상시 watcher 활성화·배포·로봇 주행은 이번 작업에서 수행하지 않았다.
