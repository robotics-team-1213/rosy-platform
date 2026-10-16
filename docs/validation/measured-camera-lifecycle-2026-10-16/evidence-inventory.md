# 실측 교정과 마커 공백 대응의 기존 근거 점검

2026-10-16. 조사 revision: `a1a183379`.
브랜치: `docs/camera-calibration-lifecycle`.
읽기 전용 문서·소스·로컬 자료 조사다. 원격 장치 접근·촬영·주행·새 pytest는 실행하지 않았다.

## 기존 결과가 증명하는 범위

| 근거 | 확인한 것 | 증명하지 못하는 것 |
|---|---|---|
| [D-636 결과](../compact-camera-calibration-2026-10-11/result.md) | ade31911c0에서 오프라인 실측 후보 도구와 합성 pinhole/fisheye/floor 검증, 표적 출력, 지도 영상 valid mask 및 브라우저 검증이 기록됨 | 인쇄 치수·실물 AprilGrid 촬영·고정 렌즈 조건·독립 바닥 측량·운영 measured admission |
| [D-587 마커 방향 설치](../ceiling-marker-yaw-2026-10-10/result.md) | 당시 설치된 기존 paint 교정으로 두 로봇의 approved_record sighting과 guide LOCALIZED를 읽은 기록. 마커 offset 설치 및 정지 반복성 표본 포함 | 현재 서비스의 설치 상태, 새 비선형 렌즈 프로필의 정확도, 측량 정답과 비교한 전체 지도 정확도 |
| [지도·핀 경로 결과](../fleet-map-stability-2026-10-11/README.md) | 핀과 odom 좌표 변환·불일치·재시작·신선도 제한의 원격 계약 시험. 당시 현장 읽기에서는 두 로봇 offline | 실제 핀으로 로봇을 추종한 현장 수용, D-593 전 구간 물리 정확도 |
| Fleet 로그의 D-596 항목 | LED 능동 확인 구현과 현장 프레임 재생 범위 | 현 시점 실물 LED challenge→프레임 판정→identity readback의 독립 검증 |
| World `map_pose.py`, Fleet `identity_triggers.py` | 기존 odom 다리와 고정 거리당 오차 trigger 존재 | D-598의 로봇별 오차 한도 상태·감속·현장 수용. 기존 `source=bridged`는 새 상태가 아님 |

역사 결과의 시험 수를 이번 revision의 새 시험 결과로 합산하지 않는다. 기존 현장 기록이
있다는 이유로 현재 카메라·map·설치 revision을 같다고 가정하지 않는다.

## 로컬 자료 조사

실행: PowerShell에서 Python 표준 라이브러리 `os.walk`, `json.loads`, `Path.is_file`을
사용한 읽기 전용 inventory 두 번. 두 명령 모두 exit 0.

범위는 공유 제품 checkout의 `data/`, `private/`, 우산 폴더의 `artifacts/device-evidence/`,
현재 호스트의 외부 scratch다. 디렉터리 깊이는 최대 6단계, `.git`, `.worktrees`,
빌드·설치·venv·release 디렉터리는 제외했다. 경로에 calib/aprilgrid/camera-calibration/
lens-candidate/floor-measurement가 있는 파일만 대상으로 삼고, JSON은 최대 2 MB까지만 읽었다.
비밀값·장치 주소·개인 파일명·JSON 값은 출력하지 않았다.

| 조사 위치 | 관련 파일 | training/validation 이미지 목록이 있는 manifest |
|---|---|---|
| 제품 `data/` | JSON 3개, JSONL 2개 | 확인한 JSON 3개 모두 해당 목록과 source/K/D/floor 후보 필드 없음 |
| 제품 `private/` | 필터에 맞는 파일 없음 | 발견하지 못함 |
| device-evidence | 필터에 맞는 파일 없음 | 발견하지 못함 |
| 외부 scratch | 필터에 맞는 파일 없음 | 발견하지 못함 |

이 필터·깊이 밖 자료, 다른 PC, 이전 기록의 X: 작업 세션은 조사하지 않았다.
따라서 자료가 어디에도 없다는 결론이 아니다. 현재 조사로 실측 후보를 승인하거나
새 좌표 정확도를 계산할 수 있는 완전한 입력 묶음을 확보하지 못했다는 결과다.

## 다음 작업에 필요한 입력

- D-636 촬영 절차에 따른 같은 source·고정 촬영 조건의 실제 표적 원본과
  서로 겹치지 않는 training/validation manifest. 기존 도구는 최소 8/2장을 요구하지만
  장수 충족 자체는 정확도 보증이 아니다.
- 실측 판 치수와 source·lens·JPEG 픽셀 공간의 조건 기록. K/D와 연결된 별도 바닥 anchor 및
  겹치지 않는 독립 check point, 실제 지도 기준점·축척 측량 근거.
- 마커 관측에는 별도의 카메라 자세·마커 높이/offset 검증. 바닥 plane 변환을
  높은 마커에 그대로 적용하지 않는다.
- D-598에는 현재 설치에서의 마커·핀·LED 현장 readback과 실제 운행 속도별
  odom 오차·마커 공백 분포. 과거 한 구간의 반복성을 전체 지도 오차로 확대하지 않는다.

사용자 설계 검토 뒤 첫 구현 단위의 계획을 작성한다. 자료가 없는 동안 source의
수치 검증·저장·철회 경로는 이후 구현할 수 있지만, 실제 입력 없이 현장 정확도나
마커 공백 주행의 수용을 선언하지 않는다.
