# 인식 프로토타입 스크립트 (검토 전)

**이 폴더의 스크립트는 리뷰를 거치지 않은 프로토타입이다.** 2026-09-24 세션에서 실물 카메라를 추정하고
현재 인식을 실물 영상으로 재생할 때 쓴 스크립트를 그대로 옮겼다. 바꾼 것은 경로뿐이다(절대 경로를 저장소
기준 경로와 환경 변수로). 로직은 바꾸지 않았다. 시험이 없고, 결과를 합격 증거로 쓰지 않는다.

- 이 스크립트가 만든 숫자: [실물 영상 기준선](../../../docs/validation/perception-real-video/2026-09-24/baseline.md),
  [카메라 프로필 초안](../../../docs/validation/perception-real-video/2026-09-24/camera_profile_draft.json).
- 실행 순서와 게이트: [D-205](../../../docs/adr/D-205-real-lane-mission-transition-order.md).
- D-205 P2의 검토된 `perception_replay` 도구가 `realrun/`을 대체한다. 그때 이 폴더는 지운다.

## 실행 환경

Windows 호스트에서 `python`으로 돌린다(ROS 불필요). `opencv-python`과 `numpy`가 필요하다.

- 입력 영상: `data/teleop/learning/teleop_20260919_151213_part01..07.mp4`. 다른 곳이면 `ROSY_TELEOP_DIR`.
- 카메라 프로필: `realrun/`은 기본으로 위 프로필 초안을 읽는다. 바꾸려면 `ROSY_CAMERA_PROFILE`.
- 출력: 모든 스크립트가 **현재 작업 폴더**에 쓴다(`out/`, `*.pkl`, `*.json`). 저장소 밖의 빈 폴더에서
  돌린다. 결과물은 커밋하지 않는다.

```powershell
mkdir X:\tmp\perception-proto; cd X:\tmp\perception-proto
$T = "F:\Dev\Control\Robot\ROS\Rosy\Rosy OS\tools\perception\prototype"
python "$T\realrun\replay.py" 1 16     # part 1의 앞 16프레임
```

## `realrun/` — 현재 인식을 실물 영상으로 재생

저장소의 `src/core/control` 인식 코드를 읽기 전용으로 import 한다.

| 파일 | 하는 일 | 실행 |
|---|---|---|
| `replay.py` | 한 영상을 `centre`·`line`·`lane`·`road` 모드로 재생한다. 벽 마스크, 대체 시각 오도메트리(바닥 KLT → 바닥 평면 → RANSAC 강체), 프레임별 `out/frames_pNN.jsonl`, 오버레이 영상, `out/raw/pNN/*.jpg` | `python replay.py <part 1..7> [max_frames]` |
| `analyze.py` | 7개 `frames_pNN.jsonl`을 모아 `out/summary_stats.json`과 표를 낸다. 7개가 모두 있어야 한다 | `python analyze.py` |
| `whatif.py` | `centre` 모드를 문턱 140/150/165로 다시 돌린다(파라미터 민감도) | `python whatif.py <part>` |
| `stills.py` | `out/raw`에서 고른 16프레임에 설명을 붙여 `out/stills/`에 쓴다. `replay.py` 뒤에 | `python stills.py` |
| `geom.py` | 실물·시뮬 카메라의 BEV 관측 범위와 거리별 영상 행을 출력한다 | `python geom.py` |
| `vo_test.py` | 합성 바닥 질감으로 대체 시각 오도메트리를 확인한다(약 1 mm / 0.1°) | `python vo_test.py` |

WSL 전용 경로가 박힌 `transcode.sh`는 옮기지 않았다. 브라우저용으로 바꿀 때는
`ffmpeg -i overlay_pNN_mp4v.mp4 -c:v libx264 -pix_fmt yuv420p -movflags +faststart overlay_pNN.mp4`.

## `camcal/` — 영상에서 실물 카메라 추정

`common.py`(영상 프레임 읽기), `getframes.py`(한 프레임 읽기), `cammodel.py`(핀홀 + 기울기·롤·높이 카메라 모델)는
다른 스크립트가 import 하는 공용 파일이다. 중간 결과(`*.pkl`, `*.json`)를 현재 폴더에 쓰고 읽으므로 순서가 있다.

| 순서 | 파일 | 하는 일 | 읽음 → 씀 |
|---|---|---|---|
| 1 | `findcw.py` | 횡단보도 막대 4개가 보이는 프레임을 찾는다 | 영상 → `cw_frames.pkl` |
| 2 | `cwcorners.py` | 막대 모서리를 부화소로 잡는다(CAD 26x121 mm, 40 mm 간격) | `cw_frames.pkl` → `cw_corners.pkl` |
| 3 | `calib.py` | 모서리로 초점거리·자세를 맞춘다(fx, 높이, 기울기, 롤) | `cw_corners.pkl` → `calib_cw.pkl` |
| 4 | `horizon.py` | 프레임별 차선 소실점을 LSD + RANSAC으로 구한다 | 영상 → `vp_rec.pkl` |
| 5 | `vpstats.py` | 소실점으로 수평선 행과 기울기 분포를 낸다 | `vp_rec.pkl` → `vp_series.json` |
| 6 | `wallh.py` | 155 mm 벽의 위·아래 선으로 렌즈 높이를 푼다 | 영상 → `wallh.pkl` |
| 7 | `ring.py` | 회전교차로 링의 원형도로 초점거리를 교차 확인한다 | 영상 → `ring.pkl` |
| 8 | `distort.py` | 벽 밑선의 휨으로 렌즈 왜곡(k1)을 가늠한다 | `wallh.pkl` → `distort.pkl` |
| 9 | `bevfinal.py` | 최종 모델로 BEV를 만들고 차선 간격·선 폭을 잰다. `out/` 폴더를 먼저 만든다 | 영상 → `out/bev_*.png`, `out/bev_check.json` |
| 10 | `annotate.py` | 수평선·소실점·모서리 재투영을 프레임에 그린다 | `cw_corners.pkl`, `calib_cw.pkl` → `out/annot_*.png` |
| — | `hazards.py`, `hazsum.py` | 카펫·테이프·벽·반사·흐림 통계 | 영상 → `hazards_raw.json` → 출력 |
| — | `samefr.py` | 같은 프레임에서 벽과 테이프 밝기 비교 | 영상 → `tape_vs_wall.json` |

`cammodel.Cam`의 기본값(피치 8.09°, 높이 69.4 mm)은 추정 중간값이다. 최종 초안 값은 프로필 JSON을 따른다.
