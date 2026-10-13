# 지도 없는 조사와 통합 관제 · 2026-10-12 사이트 검증

대상: D-655, `feat/mapless-fleet-control`, 기능 릴리스 `5f4040f306`, `site-5f4040f306bf`. [실행 계획](../plans/2026-10-11-mapless-fleet-control.md)의 Task 1~6을 소스·원격 시험·CI·서명 설치·실제 사이트 화면 범위에서 확인했다. 실물 주행·측량 정확도·대형 수용은 미확인이다.

## 증거와 범위

| 단계 | 확인한 결과 |
|---|---|
| 소스·계약 | D-655 조사 기준·시설·근거·CAS, API Reference v1.209; 기존 map body/hash 및 CORE 최종 명령 권한 유지 |
| 착지 회귀 | 원격 AI PC 자원 기준 통과. 9,320 + 3,552 + 3,651 = 16,523 PASS, NEW 0. Node 312 PASS. 별도 pre-push 원격 292 PASS |
| exact SHA CI | [FULL CI](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38151217132) completed/success, 15 jobs. [site build](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38151217060) build/attest/publish 성공 |
| 서명·설치 | 기존 운영자 signer가 동일 source/manifest를 서명. 기존 사이트 updater timer exit 0, 설치 candidate 동일 source. Fleet/Vision/proxy immutable tag·image identity 및 세 container healthy 확인 |
| 설치 소비 | Fleet SurveyReference/RoadEvidence/SiteFacility와 Vision compact calibration detect_grid/fit_lenses/fit_floor import PASS |
| 실제 UI | 원격 Chromium으로 사이트 자체 화면 1440/390 px 확인. JS 오류 0, 가로 넘침 0, 아래 시나리오 PASS |

원격 pytest는 커밋된 HEAD를 기존 `tools/remote/remote_pytest.py`로 실행하고 `test/known_failures.py`로 비교했다. 노트북 pytest나 로봇 이동으로 확인하지 않았다. exact SHA CI와 설치 proof는 다른 세션의 후속 main 기능과 구분한다.

실제 Docker `.Image`는 OCI manifest digest이고 signed manifest의 `image_id`는 config digest다. 첫 readback의 직접 동일성 검사는 실패했다. 기존 설치 검증기 `_archive_image_ids`를 통해 현재 tag의 read-only image archive와 signed config ID의 연결을 확인했다. tag 이름만으로 수용하거나 서명·identity 검사를 약화하지 않았다.

## 실제 사이트 시나리오

| 목표 | 현장 관찰 및 원격 시험 근거 |
|---|---|
| G1 빈 지도 | 기존 운영 지도를 바꾸지 않고 측정 기준의 빈 로컬 조사 초안을 생성. 초기 요소 0. 저장·재조회·CAS·활성화 거절은 원격 API/브라우저 시험 |
| G2 시설·도로 | 장소 두 개, 도로 하나, 해당 도로의 가상 신호 시설 하나를 로컬 초안에 작성. 네 요소와 SVG 아이콘 확인. dangling reference·기하·금지 영역·review 검증은 원격 시험 |
| G3 관측 축적 | 카메라 출처/촬영/교정/기준 revision 및 명시 endpoint, relative odom 시작 기준·공백/reset·CAS 검증 통과. 실물 새 관측·주행 축적과 정확도는 미확인 |
| G4 배정 | rosy_41 선택을 기록 화면에 전달하고 대상 값 확인. 선택만으로 명령 없음. 접수와 실제 진행·종료 구분 및 충돌 가드는 원격 시험 |
| G5 대형·개입 | 선택 작업 영역에서 기존 대형 패널 진입 확인. 팔로워 단독 명령·trip 충돌·활성 지도 busy guard·개입 ACK/readback 계약은 원격 시험. 오프라인 실물 대형 실행 미확인 |
| G6 화면 안정 | 좌표/오버레이/원본 세 모드 각각 세 번 관측: desktop 지도 영역 835×552 px, mobile 340×429 px. 모드 전환 중 크기 동일. 글자 중심 상태 설명은 지도 밖에 배치 |

배포 전 baseline과 최종 active/draft/profiles 응답 본문을 전체 비교해 동일함을 확인했다. 활성 `map_v2_fleet` v5, 기존 `260919 MAP FILE.STL` 계보, 저장 profile `map_v2_fleet-v5`, draft 없음이 유지됐다. 실제 저장/활성화는 운영 지도 보존을 위해 현장에서 수행하지 않았으며 별도 원격 시험 근거다.

네트워크 쓰기는 기존 개발 세션, 가상 신호 presence heartbeat, 영상 preview lease에 한정했다. 목표·주행·대형·신호 command·지도 저장/활성화 요청은 없었다. 두 로봇은 오프라인으로 위치/안전 상태를 unknown으로 유지했다. E-Stop 해제나 시험 이동을 하지 않았다.

## 교정·AI 및 책임

D-636의 작은 AprilGrid 교정 도구가 배포 Vision에 포함된다. 부분 촬영 grid, pinhole/fisheye 적합, 독립 holdout/coverage, rectified ray와 floor homography·유효 mask를 구분하는 도구의 소스/시험과 설치 import를 확인했다. 실제 grid 촬영·렌즈별 오차·유효 바닥 영역의 정확도 수용은 아직 없다. 촬영되지 않은 공간은 확정 로봇 좌표로 복원하지 않는다.

Rosy Cam은 출처·시각이 있는 관측, Vision은 검출/교정 후보, World는 좌표 투영·연속성, Fleet은 검토·배정·admission·개입 원장, CORE는 최종 actuation을 소유한다. AI 후보는 설명·검토 보조이며 survey odom 또는 추정 도로를 operational pose나 명령으로 승격하지 않는다. 새 AI provider 활성화·실제 모델 정확도 수용은 이번 증거에 포함하지 않는다.

## 검사 이력과 제한

독립 최종 화면 검토에서 Critical은 없었고 긴 페이지 캡처 세 장의 중간 헤더·skip link가 Important 증거 오류로 지적됐다. 폰트 준비·focus blur·scrollY=0 확인 후 같은 사이트에서 재캡처하고 검토자가 Important 해소를 확인했다. `logs/site-recapture.txt` terminal PASS이며 소스 수정이나 현장 명령은 없었다.

스크립트의 CSP unsafe-eval wait, 파이프 한글 인코딩, 장소 enum 가정, 기존 observational POST 누락은 검사 오류로 수정했다. CSP·권한·활성화 가드·비밀 검사 allowlist를 완화하지 않았다. 수정 전 실행을 PASS로 쓰지 않고 terminal PASS만 수용했다.

일반 IP URL은 외부 연결 시간 초과 및 인증서 IP SAN 부재가 남는다. 실제 화면은 기존 SSH forwarding과 독립 CA/SAN 검증, 같은 공개키에 한정한 Chromium trust pin으로 확인했다. 이 경로의 UI PASS는 일반 사용자 외부 접속 해결의 증거가 아니다.

로그·캡처는 공개 저장소에 넣지 않고 세션 `X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/`에 보존한다.

- `logs/land-clean/feat-mapless-fleet-control/`: 원격 회귀와 Node terminal 결과
- `logs/pre-push-fast-5f4040f306.txt`, `logs/ci-5f4040f306-terminal.json`, `logs/ci-5f4040f306-watch.txt`: push와 CI
- `release/5f4040f306bf/release.json`, `logs/site-sign-5f4040f306.txt`, `logs/site-final-readback.json`: manifest·서명·immutable 설치 proof
- `logs/site-baseline-map-state.json`, `logs/site-acceptance-5f4040f306-pass.txt`, `screens/final/map-state.json`: 기존 상태 보존과 terminal UI 결과
- `screens/final/`: 세 모드 desktop/mobile, 선택 로봇, 대형 작업 영역, 지도 편집, 빈 조사 및 시설 SVG

## 다음 실물 확인 순서

1. 로봇 연결·신원·CORE 안전 상태를 읽고 위치 신뢰 기준을 확보한다.
2. 작은 grid 여러 방향 촬영과 별도 바닥 실측 점으로 렌즈/투영 정확도·유효 영역을 평가한다.
3. 명시 기준에서 카메라·주행 조사 기록을 만들고 관측 공백·reset에서 연결이 끊기는지 확인한다.
4. 조사·도로 검토와 별도 활성화를 거친 뒤 승인된 현장 절차로 목적지·문제 개입·대형 실행과 최종 readback을 수용한다.

실물 조건이 준비되기 전에는 사이트/원격 증거를 FIELD PASS로 승격하지 않는다.
