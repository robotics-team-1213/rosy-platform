# Pinky behavior comparison implementation plan

**Goal:** 검증된 기존 녹화를 세션 단위로 분리해 실제 영상→기록된 CORE 속도 모델을 비교한다.
**Architecture:** `learning/training/pinky`는 curation 검증기를 직접 실행한다. train-only
정규화, 고정 eval 세션, 원본 hash, 모델 save/reload와 단위별 MAE를 남긴다.
**Tech Stack:** Python 3.12, numpy, OpenCV, CPU PyTorch. 장치/ROS/네트워크 접근 없음.

## 선택

상수 평균·zero baseline, 저해상도 RGB ridge, 작은 CNN을 같은 프레임으로 비교한다.
ACT는 긴 chunk/목표 의미가 아직 없고, 현재 동시각 기록 명령의 학습 가능성을 먼저 확인해야 한다.
프레임 무작위 split 대신 2 train 세션/1 eval 세션을 명시한다. 같은 Episode나 같은 raw
source session을 다른 revision으로 재포장해 eval에 넣는 것도 거부한다.
고정 eval에는 튜닝하지 않으며 CNN steps/seed, ridge penalty/resize/stride는 실행 전 고정한다.

## 작업

1. disjoint split, per-channel errors, zero/moving subsets, 모델 reload 회귀 시험을 RED로 작성한다.
2. `comparison_job.py` 구현: 3개 원본 직접 검증, 같은 영상/sidecar index 정렬,
   선택 프레임의 cmd 누락 제외 수 명시, train-only target 평균/std, ridge·CNN 학습.
3. 해시 묶인 config·검증 보고서·평가 prediction·model 파일을 X 새 디렉터리에 저장한다.
   실패 상태와 부분 산출물은 보존하며 ready/승격/dispatch는 만들지 않는다.
4. native 작은 fixture 시험과 실제 3-session 학습, 독립 리뷰·소스/호스트 증거를 남긴다.
5. ownership 매니페스트/CI selector에 새 경로를 연결하고 영향 검사 후 로컬 커밋한다.

속도는 expert intent가 아니라 기록된 CORE 최종 출력이다. 세션 수·과제·환경 다양성,
실물 camera identity/calibration, pixel 진위, owner·stale·task 수용은 별도 미확인이다.
PolicyArtifact 필수 camera calibration SHA를 만들지 않는다. 결과는 연구 비교이며
관측치 범위로 안전 엔벌로프를 정의하거나 offline MAE로 운영 승격하지 않는다.
