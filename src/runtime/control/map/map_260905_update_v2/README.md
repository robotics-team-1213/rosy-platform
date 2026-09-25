# MAP 260905 — Gazebo·Nav2 업데이트 패키지 v2

작성일: 2026-09-20  
대상: 업로드한 `map_260905.world` / Gazebo Sim Harmonic·ROS 2 Jazzy 검토 기준

**벽 형상은 유지했습니다. 월드의 치수 설명·엔진 지정과 문서를 정리하고, 주행 설정은 시뮬레이션용 선택 패치로 분리했습니다. 실제 로봇에 적용 완료된 설정이 아닙니다.**

## 먼저 볼 문서

| 문서 | 내용 |
|---|---|
| [주의사항·적용 절차](docs/01_GAZEBO_NAV2_CAUTIONS.md) | Gazebo, 좌표계, 센서, 실기 분리, 실행·복구 방법 |
| [파라미터 기준표](docs/02_PARAMETER_REFERENCE.md) | 값·단위·의미·시험 제안·유지해야 할 기준 |
| [검증 체크리스트](docs/03_VALIDATION_CHECKLIST.md) | 시험 조건, 예상 결과, 수집 증거, 미확정 기준 |
| [검증 결과 양식](docs/validation/RESULT_TEMPLATE.md) | 팀에서 실행 결과를 기록할 MD |
| [출처·판단 범위](docs/SOURCES.md) | 업로드 원본과 공개 문서의 구분 |
| [변경 이력](CHANGELOG.md) | 원본 대비 변경 및 보류 항목 |

## 파일 사용 구분

- Gazebo: `worlds/map_260905.world`
- Nav2 지도: `maps/map_260905.yaml` + `maps/map_260905.pgm`
- 사람용 도면: `review/map_260905_plan.svg` / `.png`
- 원본 보관: `original/map_260905.world`
- 설정 제안: `config/*.patch.yaml` — **완성된 Nav2 설정 파일이 아닙니다.**
- 설정 준비 도구: `scripts/prepare_sim_params.py`
- 정적 검사: `scripts/validate_bundle.py`, `tests/test_prepare_sim_params.py`
- 검사 결과: `reports/` / 무결성 목록: `MANIFEST.sha256`

원본 월드에는 로봇 모델·실제 footprint·LiDAR 설치 높이·프로젝트 안전 임계값이 없습니다. 공개 Pinky 설정을 우리 프로젝트의 확정값으로 복사하지 않았습니다. [출처 F1, P1](docs/SOURCES.md)

## 변경 요약

| 항목 | 처리 |
|---|---|
| 16개 벽의 위치·두께·높이·회전·충돌/시각 형상 | 유지 |
| 월드 주석 | 형상 외곽 2.715 × 1.265 m, 벽 두께 10 mm로 명확화. 실측 확정이라는 뜻은 아님 |
| 물리 엔진 | Physics 시스템에서 DART 플러그인 명시. `physics` 이름 추가 및 `type="dart"` 정렬 |
| 1 ms timestep·마찰값·재질·바닥·GUI | 유지. 실제 적용 효과와 실행은 미검증 |
| 점유 지도 | 5 mm 격자로 재생성. 이전 지도와 픽셀 동일성 검사 |
| Goal/Planner·지도 설정 | 기본 시뮬레이션 패치 |
| RPP 저속·lookahead·비용 감속 | 추가 검토 후 선택 적용 |
| Progress checker | 별도 승인 후 선택 적용. 기존 timeout 유지 |
| 실제 모터·LiDAR guard·footprint·안전거리 | 변경하지 않음 |

## 적용 순서

1. `original/`을 보관하고 새 `worlds/`와 `maps/`를 검토합니다.
2. 실제 전체 `nav2_params.yaml`과 전개된 URDF를 확인합니다.
3. 준비 도구를 **쓰기 옵션 없이** 실행해 변경 예정값을 먼저 확인합니다.
4. 검토 후 새 파일로만 저장하고, 분리된 시뮬레이션에서 검증합니다.

패키지 루트에서:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

python scripts/validate_bundle.py
python -m unittest discover -s tests -v

# 실제 사용하는 전체 Nav2 YAML의 경로로 지정합니다.
export BASE_NAV2="/absolute/path/to/your/nav2_params.yaml"
python scripts/prepare_sim_params.py --base "$BASE_NAV2"
```

실행·저장 명령과 선택 패치 승인 절차는 [주의사항 문서](docs/01_GAZEBO_NAV2_CAUTIONS.md)에 있습니다. 도구는 원본 YAML을 덮어쓰거나 ROS 명령을 발행하지 않습니다.

## 검증 상태

**수행 범위:** XML 파싱, 모델 보존 비교, 지도·좌표·연결성 검사, 파라미터 준비 도구의 로컬 단위시험. 상세 결과는 `reports/package_validation.json`과 `reports/unit_test_results.txt`를 확인합니다.

**미수행:** `gz sdf` 검증, Gazebo 실행, 실제 설치 플러그인 로드, ROS/Nav2 주행, 센서 실측, 실기 안전 검증. 작업 환경에 `gz`와 `ros2` 실행기가 없습니다.

정적 검사 PASS는 자율주행 또는 실기 안전 승인과 다릅니다. 미확정 안전값은 `config/safety_review_template.yaml`에서 `null`로 남겨두었습니다.
