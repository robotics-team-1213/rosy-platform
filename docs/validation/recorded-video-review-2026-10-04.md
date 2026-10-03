# 기존 촬영 영상의 라벨 검수 패키지

2026-10-04 KST. 사용자 요청: 기존 촬영 영상에 벽·신호등·장애물이 있으므로
그 영상을 바탕으로 라벨과 학습 데이터를 보강한다.
[클래스 설계](../plans/2026-10-04-perception-class-expansion-design.md)의 실제 데이터 준비 기록이다.

## 영상 확인

모델 PC의 기존 data/teleop/learning에서 MP4 19개를 확인했다.
각 영상의 상대 시간과 프레임 번호를 표시한 9장 contact sheet를 만들고,
10개 영상의 90개 샘플과 일부 원본 프레임을 직접 읽었다. 전체 영상의 완전 검수는 아니다.

관측: 차선·벽·횡단보도, 사람 발, 다른 Pinky 로봇,
신호등 조립체 후보와 작은 원거리 물체. 벽의 파란 테이프·녹색 표식,
바닥의 노랑/검정 표식·붉은 케이블은 차선 오인/장애물 구분 검수에 활용한다.
노랑/검정 표식의 색만으로 실제 과속방지턱 형상이나 정답을 확정하지 않았다.
신호등 조립체 후보의 색 상태는 작은 해상도로 확정하지 않고 unknown으로 남겼다.

9월 19일 part01~07은 같은 원본 녹화에서 나뉜 파일이므로 하나의 capture group이다.
9월 28일 legacy 201 영상 두 개도 보수적으로 같은 날짜의 capture group으로 묶었다.
확인되지 않은 역사적 CameraProfile·header stamp·bag log time은 만들지 않았다.

## 생성한 산출물

| 원본 | 추출 프레임 | 제안 split |
|---|---:|---|
| 20260919 part01 / part04 | 12 / 12 | train, 동일 group |
| 201 20260928 215056 / 215522 | 16 / 16 | val, 동일 group |
| 9dfk 20260930T171014Z | 20 | train |

총 76프레임. 2026-10-01의 두 고정 평가 세션은 사용하지 않았다.
이 제안 split은 group 누출 방지를 위한 검수 준비이며 아직 학습 데이터셋 승인이 아니다.

- frames.jsonl: 원본 파일/프레임·상대 시간·원본 크기·JPEG SHA·capture group·pending 상태.
- review_manifest.json: 원본 MP4 SHA·fps·녹화 group 근거·예약 평가 세션.
- lane-drafts/: 소형 모델 `lane-seg-20261004-f21a7a97`의 76개 mask 초안,
  preview, ranking.csv, 이미지 및 CVAT Segmentation mask 1.1 import zip.
- object-drafts.jsonl: 직접 본 원본 4프레임에 신호등/로봇/사람 발 박스 7개 초안.
  annotation_source=assistant_visual_draft, pending_human, complete_frame_review=false.
  신호 상태는 unknown. 원본 4개 JPEG를 object-images/에 함께 보존했다.

기존 prelabel.py를 그대로 사용했다. 예측 mask와 AI box를 사람이 검수한
정답으로 표시하거나 object_boxes.py의 human 입력에 넣지 않았다.
물체 초안에서 빠진 물체가 있을 수 있으므로 빈 파일을 음성 정답으로 만들지 않았다.
mask의 crosswalk/stop_line 성능을 이 초안으로 새로 학습·확인했다고 주장하지 않는다.

## 검증과 검수 후 학습

76개 source JPEG SHA, CVAT mask 76개, 7개 box의 원본 크기 내 경계와
capture group의 제안 split 비겹침을 확인했다.
동일 원본의 part 파일을 서로 다른 split으로 나누지 않는다.
모델 예측을 스스로 정답으로 삼아 정확도를 측정하지 않는다.

검수 순서는 ranking.csv의 불확실 프레임, 벽/바닥 경계와 파란 테이프,
주행영역·횡단보도/정지선, 물체 box와 신호 상태다.
검수 완료 mask/box와 클래스 의미를 별도 immutable 버전으로 만든 후 재학습한다.
도로와 물체·신호 상태는 각각 IoU, precision/recall, 상태 confusion/시간 지연으로 평가한다.

모델 PC `~/rosy-ml/pipeline-closure-20261004/recorded-video-review-v1/`와
로컬 `X:/DevTemp/rosy-learning-audit-20261004/recorded-video-review-v1/`에 보존했다.
완성 bundle `recorded-video-review-v1-complete.tar.gz` SHA-256:
`e1b245a7cfd1969923e42de32c029153d62ebf1ce461f0e5a681231725b2f365`.
초기 bundle에는 별도 물체 원본 JPEG가 빠져 있었고 완성 bundle에 추가해 해시를 새로 기록했다.
영상을 공개 저장소에 올리지 않았다.

이번 결과는 실제 영상 확인·라벨 초안·검수 패키지 생성 증거다.
새 물체/신호 모델 학습 및 수용은 미완료이며 전체 목표는 active다.
