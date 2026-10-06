# Qwen 점 → SAM 3 전파로 차선·도로 픽셀 초안 만들기 (설계)

**날짜:** 2026-10-06
**상태:** 설계 승인(사용자, 2026-10-06). 구현·설치·착지 승인 아님.
**관련:** D-379(기하 자동 라벨), D-462/D-464(픽셀 검수·학습 자격), D-465(모델 PC 픽셀 초안), D-475(평가 정답·drivable 정의)

## 목적

D-379 자동 라벨은 벽·바닥은 LiDAR로 믿을 만하지만 drivable은 주행 궤적 0.10 m 띠뿐이다. D-475 §8의 drivable(흰 경계선 안쪽 보이는 도로 전체)과 다르다. 차선도 기존 모델 초안은 과노출·카펫 무늬에서 틀린다(2026-10-06 spin 세션). 이 설계는 lane_line과 drivable 초안을 사람이 덜 고치게 만드는 것이 목표다.

## 파일럿 결과와 수정된 구조 (2026-10-07)

모델 PC 파일럿(세션 `20261006T091340Z_rosy_26`, 키프레임 20장 + 연속 642프레임 8 fps)에서 아래 절의 원래 구조 일부가 바뀌었다. 이 절이 아래 ①~④와 다르면 이 절이 우선한다.

| 원래 설계 | 파일럿 결과 | 수정 |
|-----------|-------------|------|
| lane_line을 Qwen 점 → SAM으로 | Qwen 선 점이 화면 가장자리·하단에 환각 열을 만들고 gate가 약 45% 버림. lane 6.1%, 미라벨 30.6%. SAM 3 텍스트 "white line"(rosy-42 v3)이 훨씬 깨끗함(lane 10.8%, 연속 IoU 중앙값 0.991) | **lane_line·wall은 SAM 3 텍스트 프롬프트.** Qwen은 lane에 쓰지 않는다 |
| drivable = Qwen 도로 점 → SAM | SAM은 「카펫」을 분할할 뿐 「도로」를 구분하지 못함. Qwen 점이 흰 선 너머 띠(벽 앞)에 몰리면 로봇 앞 도로가 빠지고 선 너머가 drivable이 됨 | **drivable seed = 로봇 바로 앞 카펫(하단 중앙, D-379 footprint 원리) + Qwen 도로 점.** 최종 drivable = 흰 선(1px 팽창)을 넘지 않고 로봇 발판 띠와 겹침이 가장 큰 카펫 연결 성분. 선 너머 카펫은 base 값 유지(D-475: 도로 밖 바닥은 floor), 사람이 판단 |
| Qwen JSON 스키마 프롬프트 | 6장 중 5장 빈 결과 | Qwen 고유 `point_2d` 형식 + 3× 업스케일(320×240은 시각 토큰이 너무 적음) + `num_predict` 600 상한(없으면 160 s 폭주) + 정규식 파싱 |
| 재시드 조건 3가지 | 고정 15프레임(1.9 s) 재시드로 경계 IoU 중앙값 0.989 | 고정 K=15로 시작. 조건부 재시드는 필요가 측정되면 추가 |

측정(642프레임, RTX 5080 16 GB):
- 속도: SAM 텍스트 lane 0.21 s/frame + tracker drivable 0.22 s/frame, Qwen 키프레임 평균 2.8 s(43장). peak VRAM 7.5 GB(SAM 영상·이미지 모델 동시). Qwen과 SAM은 같은 시간에 올리지 않는다(Qwen `keep_alive: 0`로 내림).
- 안정성: drivable 연속 프레임 IoU 중앙값 0.998, p10 0.902, 0.5 미만 전환 5/641, 빈 도로 프레임 0.
- 면적 평균: road(drivable) 29.1%, 선 너머 카펫(drivable 아님, 사람 판단) 15.6%, lane 10.3%.
- 남은 오류: 노란 경사로 일부, 프레임 가장자리 회색 바닥 조각, 로봇이 선 위에 걸칠 때 발판 성분 선택이 갈림(전환 5건).

수정된 흐름:

```
mp4 → 연속 프레임
  SAM 3 이미지 텍스트 "white line"/"wall" → lane_line, wall (프레임마다)
  K프레임마다: 발판 seed + Qwen point_2d 도로 점 → 밝기·lane gate
  SAM 3.0 tracker: 키프레임 seed → K프레임 전파
  drivable = closing(track) − lane − 노란색, 로봇 발판과 연결된 성분만; 나머지 카펫은 base 값 유지
  → indexed PNG → verified-inputs → review_ingest
```

파일럿 스크립트는 모델 PC `~/rosy-ml/qwen-sam3-pilot/`(`a_points.py`, `b_sam.py`, `c_keypoints.py`, `c_track.py`, `d_robot_road.py`)에 있고, 저장소 이식은 구현 계획에서 한다.

## 범위

- 대상 클래스: `lane_line`(1), `drivable`(3). `wall`(2)·`floor`(0)는 D-379 결과 그대로. `stop_line`·`crosswalk`는 이번 범위 밖.
- 산출물은 **학습용 초안**뿐이다. 자동 승인 없음. 평가 정답 경로는 아래 「평가셋」 절.
- 실행 위치: 모델 PC(D-434). 소스: `learning/training/perception/dataset/`.

## 흐름

```
세션 frames/ + D-379 masks/
  ① point_draft.py   Qwen3-VL(Ollama) → 키프레임 클래스별 점
  ② gate_points()    D-379 마스크로 점 검사 → 통과한 점만
  ③ sam3_mask_draft.py  SAM 3.1 비디오 예측기: 키프레임 seed → 전파 → 재시드
  ④ compose_class_map() lane/drivable + D-379 wall/floor → indexed PNG(255 = 미확신)
  ⑤ verified-inputs.jsonl → review_ingest (기존) → 사람 승인 → review_dataset → build → 학습
```

### ① 점 찍기 — `point_draft.py`

- 모델: `qwen3-vl:8b-instruct`(Ollama, 모델 PC 로컬). `reasoning_effort: none`, `OLLAMA_CONTEXT_LENGTH=8192`(2026-10-06 파일럿 교훈).
- 요청: 흰 경계선마다 3~6점(선마다 `track_id` 구분), 선 안쪽 도로 2~3점, 도로 밖·벽 음성점 2개.
- Qwen3-VL 좌표는 0–1000 상대값 → 원본 픽셀로 변환. (`vision_draft.py`의 픽셀 가정은 이 경로에 쓰지 않는다.)
- 출력 `points.jsonl` 행: `{index, image_sha256, class, track_id, points: [[x, y, +1|-1], ...], model, prompt_id}`.
- 키프레임에서만 호출(③의 재시드 프레임 포함).

### ② 점 검사 — `gate_points()` (numpy, GPU 없음)

D-379 마스크와 프레임 밝기로 각 점을 확인한다.

| 점 | 남기는 조건 |
|----|------------|
| lane_line + | D-379가 floor 또는 lane_line으로 본 픽셀 **그리고** 밝은 픽셀(임계값은 프레임 floor 밝기 기준 상대값) |
| drivable + | D-379 floor/drivable **그리고** 밝지 않음 |
| 음성 − | D-379 wall, 또는 floor이면서 lane 바깥 |
| D-379가 255 | 판단 불가 → 버림 |

선 하나(`track_id`)에서 통과한 양성점이 2개 미만이면 그 선은 버린다. 목적: Qwen 오검출(삼각대 다리, 벽 균열 — 2026-10-06 파일럿)이 SAM seed가 되지 않게 한다. VLM은 후보를 내고, 채택은 센서가 정한다.

### ③ SAM 3 전파 — `sam3_mask_draft.py`

- SAM 3.0 비디오 모델의 tracker(`facebook/sam3`, `sam3.pt`; `build_sam3_video_model().tracker`, SAM 2식 `add_new_points_or_box` → `propagate_in_video`). 선마다 object id 하나, drivable 영역 object id 하나.
- SAM 3.1(multiplex)을 쓰지 않는 이유(2026-10-06 모델 PC 스모크): 고정 커밋 2345a4ad에서 `start_session`이 multiplex `init_state`가 받지 않는 `offload_state_to_cpu`를 넘김, 점 프롬프트만으로 객체 0개, 텍스트 경로는 16 GB에서 OOM. multiplex의 이득(많은 객체 동시 추적)은 객체 2~4개인 이 작업에 작다. SAM 3.0 tracker 측정: 320×240 23프레임, 0.20 s/frame, peak VRAM 4.2 GB, 바닥 점 하나로 회전 중 바닥 영역을 삼각대·벽·케이블을 빼고 추적.
- 키프레임에 ②의 점을 넣고 이후 프레임으로 전파한다.
- 재시드(그 프레임에서 ①②부터 다시) 조건, 하나라도 맞으면:
  - 마지막 seed 후 15프레임
  - lane 마스크 픽셀 중 「밝음 ∧ LiDAR floor」 비율 < 0.6
  - object 마스크 면적이 직전 프레임 대비 ×2 초과 또는 ×0.5 미만
- 세 값은 CLI 인자로 둔다(실영상에서 조정).
- 모델 적재: Qwen과 SAM을 동시에 VRAM에 두지 않는다. 세션 단위로 ① 전체 키프레임 → Qwen 내림 → ③ 실행, 재시드가 필요한 프레임은 모아서 다음 패스에서 처리한다(최대 3패스, 남은 프레임은 v2 초안 유지).

### ④ 클래스 맵 합성 — `compose_class_map()`

- `lane = SAM lane ∩ (밝음 ∧ dilate(LiDAR floor))` — 얇은 선에서 SAM이 번지는 것을 자른다.
- `drivable = SAM drivable − lane − D-379 wall`
- wall/floor는 D-379 그대로. 어느 출처도 확신하지 않는 픽셀은 255.
- 클래스 id는 기존 `classes.yaml`(floor 0, lane_line 1, wall 2, drivable 3, stop_line 4, crosswalk 5) 그대로.

### ⑤ 리뷰 앱 연결

- 기존 `review_ingest.py` 입력(`verified-inputs.jsonl`, `mask: {indexed_png, sha256, classes_sha256}`)을 그대로 쓴다. 리뷰 앱은 바꾸지 않는다.
- 출처 receipt(D-465 §6): Qwen 모델·프롬프트 id, SAM 체크포인트 sha256, 재시드 횟수, gate 통과/거절 수, source commit → 실행 폴더의 `receipt.json`.
- 리뷰 순서: 기존 v2 초안과 픽셀 불일치가 큰 프레임 먼저.
- `process_session.sh`의 v2 초안 단계를 이 단계로 바꾼다(실패 프레임은 v2 초안으로 남음).

## 실패 처리

- Qwen 응답 없음·JSON 깨짐·gate 통과 0 → 그 프레임은 v2 초안. receipt에 사유.
- SAM OOM·예외 → 그 세션 중단, 이미 쓴 프레임은 유지, 재개 가능. 빈 background로 바꾸지 않는다(D-465 §6).
- 어떤 경우에도 `review_status`는 `pending_human`.

## 평가셋

D-475 §7: 평가 정답 초안에 모델 출력을 쓰지 않고, SAM은 사람이 찍은 점만 다듬는다. 평가 프레임은 ①을 건너뛰고, 리뷰 앱에서 사람이 찍은 점을 ②③④에 넣는다. 같은 도구, 점의 출처만 다르다. 점 입력 UI는 이 설계의 범위 밖(후속).

## 검증

- 단위 테스트(합성 numpy 이미지, GPU 없음): 0–1000 → 픽셀 변환, `gate_points()` 표 4행, `compose_class_map()` 우선순위·255 처리.
- 파일럿(모델 PC): 20프레임 세트 + spin 세션 2개(frames 20–62). 사람이 승인한 마스크와 초안의 IoU(lane_line, drivable)를 v2 초안과 비교한다. 장당 수정 시간·처리 시간·peak VRAM·재시드 횟수·gate 거절률도 기록. 합격 수치는 실행 전에 정해 기록한다(D-465 §8).

## 문서

D-465 추가 조항: §2의 SAM 2 계열에 SAM 3/3.1(점 프롬프트, 비디오 전파)을 더하고, VLM 점은 D-379 기하 검사를 통과한 것만 seed로 쓰며 학습 초안 전용임을 적는다. 새 ADR 번호는 쓰지 않는다.

## 선행 조건

- ~~모델 PC 이더넷 연결~~ 완료 2026-10-06 (1 Gbps, 기본 경로)
- Hugging Face `facebook/sam3`, `facebook/sam3.1` gated 승인 + 토큰
- Ollama 설치 + `qwen3-vl:8b-instruct` 받기
- ~~공식 `facebookresearch/sam3` 설치~~ 완료 2026-10-06: USB 번들 `install.sh` → `~/rosy-ml/sam3-venv`(torch는 학습 venv 재사용), 번들에 빠진 `einops`·`pycocotools` 추가, 체크포인트 sha256 일치

## 하지 않는 것

- stop_line·crosswalk·객체 박스 마스크
- 리뷰 앱 UI 변경(평가용 점 입력 포함)
- 자동 승인, 평가 정답 자동 생성
- Qwen fine-tune, SAM fine-tune
