# 범용 지도 이미지·선 추출의 소스 검증

2026-10-21 기록. 결정은 [D-835](../../adr/D-835-generic-map-tracing-and-assisted-extraction.md), 요구는 MAP-205·MAP-206, 공개 계약은 API v1.293이다. 이 기록은 아래 SHA의 원격 소스 시험이며 운영 설치나 실측 수용 기록이 아니다.

## 실행 근거

모든 pytest·실제 Chromium은 승인된 원격 시험 PC에서 커밋 SHA로 실행했다. 순수 JS RED/GREEN은 Node에서도 별도 확인했다. 아래 실행들은 겹치는 시험을 포함하므로 합계를 고유 시험 수로 읽지 않는다. 각 GREEN 로그는 `test/known_failures.py` 비교에서 NEW 0·known 0·flaky 0이다.

| 시험 SHA | 명령의 시험 경로/환경 | 결과 |
|---|---|---|
| `4a2f84e1fa` | `remote_pytest.py -- test_site_map_raster.py test_site_map_projection.py test_site_map_drawing_api.py test_site_map_drawing_contract.py` (모두 operations/fleet/test) | 63 passed, 0 skipped. 원본/EXIF/알파/픽셀 한도·실측 변환·재시작·해시·HTTP 권한 및 기존 STL |
| `7ae0f2e05a` | `ROSY_RUN_BROWSER_TESTS=1`, shared transport·map_editor_browser·Console Node wrapper·remaining_platform_installed | 17 passed, 0 skipped. 토큰 인증 이미지 등록·그리기·저장·재접속, JSON 기본/오류 응답 및 wheel/sdist |
| `fdf4c60827` | `ROSY_RUN_BROWSER_TESTS=1`, map_editor_browser·Console Node wrapper·remaining_platform_installed | 15 passed, 0 skipped. 분할·연결·단일 undo/redo와 추가 자산의 실제 설치 |
| `2d3ae718e7` | `test_site_map_extraction.py test_site_map_raster.py test_site_map_drawing_api.py` | 31 passed, 0 skipped. ROI offset·직선/윤곽·빈 결과·자원 한도·immutable 후보/출처 보관 |
| `93f8408f19` | `ROSY_RUN_BROWSER_TESTS=1`, extraction·map_editor_browser·Console Node wrapper·drawing_contract·remaining_platform_installed | 43 passed, 0 skipped. 후보 수정·용도 지정·서버 검증·초안 반영·undo/redo·저장·재접속 및 시설 근거 |
| `624114525e` | `operations/fleet/test/test_site_map_extraction.py` | 8 passed, 0 skipped. 위 API 회귀와 직교·30° 회전·잡음 합성 도면의 추출 기준선 |

RED는 누락된 raster adapter 8건(`e15c2f9a7d`), binary transport/raster importer 2건(`02d8082c89`), 추출기 4건(`0ea1ba4169`), 후보 검증 endpoint 404 1건(`fd4f097ade`)을 원격에서 관찰했다. 순수 기하 split/join/snap과 후보 controller의 누락도 Node에서 확인했다. 설치 검사는 새 topology 모듈의 기존 자산 개수 기대값 누락 2건(`fbca7a5c72`)을 발견했고, 실제 membership에 모듈을 추가한 `fdf4c60827`에서 통과했다. 실패를 기존 실패 목록에 추가하지 않았다.

## 합성 기준선의 의미

`test_synthetic_line_accuracy_baseline`은 고정된 두 선을 160×160 평면 이미지에 그리고 직교·30° 회전·고정 seed 60개 잡음 점을 비교한다. 후보 양 끝점의 기준 직선에 대한 수직 오차는 2 px 이하다. 검출 후보 중 알려진 직선에 맞는 비율(precision)과 각 기준 직선이 하나 이상의 후보로 검출되는 비율(line-presence recall)이 모두 0.9 이상인 것을 확인했다. 이는 선의 전체 길이 복원율·완전한 위상·실제 도면의 정확도를 보장하지 않는다. 픽셀→지도 변환은 알려진 100 px/2 m 기준과 y 반전·회전을 별도 검사했다.

## 보존 로그 지문

원문 로그는 내부 호스트 정보가 있어 공개 저장소에 복사하지 않았다. 각 실행 디렉터리의 `run-1.txt` SHA-256이다.

| 실행 식별자 | SHA-256 |
|---|---|
| rosy-d835-raster-green | `45b055d52f16ea1e7835f00b2ca0090da3a83df476634ca0e9dd116dd47de570` |
| rosy-d835-image-ui-green | `7845a01bd6de35d9a97d88e9342ae37cd193942dc40de968ddda0f0b081c5bfd` |
| rosy-d835-topology-fixed | `2b5a95bbbe7b5ad75950568ba43ddc29184b45a3c9c011e3883e991559c2d6f3` |
| rosy-d835-extract-green | `5eea75f563c114fe0fa59ea15cb822ccc69ae036fd1fc892a7514206f8310a1a` |
| rosy-d835-review-green | `45a4e8ba8823d5619809e85451ea8e0afdd31aacbc8b0ff58b4eccb82a403146` |
| rosy-d835-extraction-baseline | `5ef04c2071a9a2b428fb5185045ae4f24e5fda64f4e9031861d7e567543a9877` |

## 경계

코드의 광범위 영향 검사는 shared foundation/의존성 변경으로 FULL에 해당한다. `eda77979b5`의 원격 affected 요청은 진행 중이며, 이 기록의 scoped GREEN으로 전체 CI를 대신하지 않는다. 독립 검토·최종 게시 head·필수/비게이팅 CI·서명/설치/runtime readback은 각각 별도 확인해야 한다.

실제 CAD/도면 인수, 원근/왜곡 교정, 현장 실측 오차, 로봇 좌표 교정, navigation·군집 이동과 FIELD는 NOT_TESTED다. AI 모델/weights는 아직 선정·평가·배포하지 않았다. 현재 후보 생성은 일반 영상 처리이며 외부 추론 전송이나 모델 프레임워크 실행을 추가하지 않는다.
