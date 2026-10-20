# OMX 파지 구간 실제 화면·내보내기 검증

2026-10-21, [실행 목표](../../plans/2026-10-21-omx-ui-walkthrough.md), [D-833](../../adr/D-833-native-omx-grasp-segments.md).

## 범위와 실행 코드

Windows의 실제 Edge 창에서 AI 시험 PC의 loopback 검수 서버를 SSH 터널로 열었다. 운영 작업공간을 사용하지 않고 새 격리 작업대와 합성 자료만 만들었다. `LeRobot 0.4.4`의 실제 writer·reader와 H.264 영상 파일을 사용했으며 프레임 API·데이터 reader를 대체하지 않았다. 원본 3 Episode × 12프레임, 독립된 synthetic session/cycle 3개, 카메라 front 256×192다. 모든 영상에 `SYNTHETIC - NO ROBOT CAPTURE`를 표시했다.

실행 소스는 `7385897cf3`이다. 브라우저가 받은 `/omx.js` 바이트를 해당 Git 커밋의 파일과 대조했다(SHA-256 `2419c6f3e5f79d302f9c1b527a90ac30bb69844d59f1283b995538d85a857f35`). Windows의 기존 Playwright는 새 Edge를 닫을 때 driver 오류가 나서 공유 환경을 바꾸지 않고 시험 전용 경로에 시험 PC와 같은 Playwright 1.64.0을 설치했다. 이후 전체 walkthrough가 exit 0으로 끝났다.

## 발견과 수정

| 재현 | 원인·수정 | 회귀 근거 |
|---|---|---|
| 프레임 HTTP 200, 이미지 `naturalWidth=0`, 실제 화면의 깨진 사진 | 기존 CSP가 `blob:` 이미지를 차단했다. 기존 허용 범위인 data URL로 읽고 CSP는 유지했다. | `5019439f59`에서 디코딩 검사 추가 후 원격 1 failed → `47f467b83d`에서 관련 3 passed. |
| Episode 변경 후 이전 Episode 사진이 남음 | 원본 선택 변경 시 사진을 숨기고 요청 version으로 늦은 결과·오류를 무시한다. | `38336e8438`에서 숨김 검사 추가 후 원격 1 failed → `7385897cf3`에서 관련 3 passed. |

독립 소스 검토는 최종 `7385897cf3`까지 수행했고 남은 발견은 없었다. 검토자는 실제 Edge 조작이나 pytest를 별도로 실행하지 않았다.

## 실제 브라우저 결과

- 원본 Episode의 프레임 2를 JPEG로 불러와 `naturalWidth=256`과 표시된 Episode·프레임을 확인했다.
- 이전 프레임 요청을 브라우저에서 보류하고 Episode를 바꾼 뒤 실제 서버 응답을 풀었다. FileReader 완료 뒤에도 이전 사진이 숨겨져 있고 원본 변경 안내가 유지됐다.
- 미판정 결과를 train으로 저장하려는 요청은 HTTP 400으로 거부됐다. 이것이 유일한 예상 HTTP 오류이며 page error·CSP 오류는 0개였다.
- 각 Episode의 원본 사진을 확인하며 `[2,6)`을 각각 train/eval/test로 저장했다. 검수자와 근거에는 agent/synthetic 시험임을 명시했다. 여러 번 재검증하며 생성된 revision도 이 격리 DB에만 남았다.
- 선택 JSON을 실제 브라우저 다운로드로 저장하고 새로고침 뒤 세 구간이 복원되는 것을 확인했다.
- desktop 1440×1000에서 문서 폭 1440, phone 390×844에서 문서 폭 380이었다. 원본·저장·복원 화면 등 PNG 7개를 캡처했고 desktop 원본/저장과 phone 복원 이미지를 직접 읽었다. 표·메뉴 내부 가로 스크롤과 페이지 전체 넘침은 구분한다.

원본 전체 Episode의 결과는 unknown/exclude 그대로다. 따라서 화면 상단의 전체 원본 `학습 불가` 상태를 구간 성공 선택으로 바꾸지 않았다.

## 다운로드에서 실제 내보내기까지

다운로드한 JSON을 `native_segments.py`에 전달해 별도 폴더로 내보낸 뒤 실제 reader와 `native_cycle.validate_split`으로 다시 읽었다. 상세 수치는 [내보내기 검증](evidence/export-verification.json)에 있다.

| 분할 | child 프레임 | 보존된 int64 clock 시작 → 끝 |
|---|---:|---|
| train | 4 | 9007199254740994 → 9007199254740997 |
| eval | 4 | 9007199254741994 → 9007199254741997 |
| test | 4 | 9007199254742994 → 9007199254742997 |

원본 파일 hashes·원본 decisions bytes가 같고, action과 2^53을 넘는 원본 clock 값이 정확히 유지됐다. child frame index는 0..3으로 다시 매겼다. exporter는 각 child 이미지가 해당 원본 프레임과 대응하는지 기존 평균 채널 오차 한도 8/255로 검사했다. 새 H.264 출력의 영상 bytes 자체가 원본과 같다는 주장은 하지 않는다. 최종 다운로드 문서와 receipt의 `segment_selection`도 같았다.

## 보존 증거와 한계

원본 캡처·실행 스크립트·JSON·remote RED/GREEN 로그는 시험 스크래치의 `rosy-hybrid-ui-20261021/`와 작업공간의 `Rosy/artifacts/receipts/omx-grasp-ui-20261021/`에 보존한다. 합성 원본·실제 내보내기·SQLite backup API로 만든 일관된 검수 DB 스냅샷은 `synthetic-walkthrough.tar.gz`(87995 bytes, SHA-256 `b2f966195c8c6a972bd148bd79126223a016fbecbc74153965ecf108db19f81a`)에 묶었다. 아래 파일 SHA-256은 이 기록 시점의 값이다.

| 파일 | SHA-256 |
|---|---|
| `02-original-frame-broken.png` | `61b7900e92f4522c38594bde5211f2a4d6078538347ae72c213972f9ddb9d863` |
| `02-original-frame.png` | `7f606b5e5917dd05ce9c737b831554b39d3e5905459e2fcee7d4a9dbdd379f90` |
| `04-saved-three-groups.png` | `f5cb4622c3159f8dfd46ef04334c9e63bdecd349dd40340bbccec6cb3c57cab4` |
| `06-phone-restored.png` | `4dc6544b92646e13e99a488a3d60bc73737537f18f58080b7d0e2d067204c1e5` |
| `selection.json` | `39e3f24ab13c7c00b9153845ad5505ef4a6843b1c47ab8825a552f91b1fe60f0` |
| `export-verification.json` | `8fd194406ede382d48f62da13d4d60db0f4e3cfe716bc38b647769fbd3dda152` |

이는 실제 화면과 파일 경로의 검증이다. 실물 촬영 자료·사람의 파지 성공 판정·팔 동작·전류 기준·카메라/LLM 판정기·모델 품질·데이터 절감률은 검증하지 않았다. 합성 구간의 success는 시험 입력이며 운영 학습 정답으로 승격하거나 모델을 활성화하지 않았다. 원격 push·배포도 하지 않았다. 로컬 main 착지는 이 기록 이후 공식 `tools/land.py --tests auto` 결과와 Git 이력으로 확인한다.
