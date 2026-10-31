# map_world_261026 (작업 중)

2026-10-26 팀 월드 CAD에서 뽑은 트랙이다. 매트는 2.44 × 1.22 m다. OMX 셀 판·컨베이어는 매트 밖에 있다. 이 트랙은 `map_v2_fleet`(2.81 × 1.26 m)를 대체할 후보다. 아직 사이트에 배포하지 않았다.

| 파일 | 역할 |
|---|---|
| `tools/calibration/extract_world_paint.py` | 월드 STL(약 85 MB, Git 밖)에서 매트 위 1 mm 차선 페인트 윗면만 뽑아 ROS 좌표(m, 매트 중심)로 바꾼다. 원본 sha256은 스크립트에 고정되어 있다. |
| `meshes/road_lines.stl` | 생성된 차선 페인트 |
| `meshes/road_lines.json` | 원본 해시, 매트 크기, 페인트 면적 |

원본 CAD 보관 위치: 작업 공간 `Rosy/docs/research/map-world-261026/`(Git 밖).

## 2026-10-31 천장 카메라 대조

`ceiling_north` 프레임에 페인트 정합(`rosy_vision.map_register`)을 돌렸다.

- 전체 페인트: 거부됐다(recall 0.71). 실제 주차 구역은 분홍·초록 테이프다. 정합 마스크는 흰 선만 본다.
- 주차 구역(y > 0.20 m)을 뺀 페인트: 수락됐다. recall 0.85, precision 0.91, coverage 0.97.
- 실제 주차 구역 모양은 CAD와 다르다. 실물은 분홍 3칸에 아래 막대가 있고, CAD는 흰 칸막이 2개와 점선이다. 오른쪽 아래 정지선 일부는 실물에 없다.

남은 일: 주차 구역 실측 반영, 차선 그래프(`lane_rules.yaml`·places·edges), 사이트 지도 JSON, 카메라 설정·배포, Nav2 지도.
