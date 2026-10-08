# 두 Pinky의 현장 몸체 ID 대조 — 2026-10-09 KST

## 범위와 설치물

- 현장 장치 두 대 모두 설치 릴리스 `2026.10.08-055`; `rosy-core`, `rosy-face`, `rosy-io`가 active였다.
- 인증된 각 로봇 Web의 `POST /api/v1/host/hardware/test` (`device: lamp`)와 `GET /api/v1/host/hardware` 결과를 썼다. Rosy Cam `ceiling_north`의 같은 회차 1280×720 프레임을 현장 Fleet Web에서 확인했다.
- 평상시 `ROSY_LAMP_ENABLED=false`였고, 자가 시험 뒤 이 설정을 변경하지 않았다. 이 시험은 정지 중 램프만 점멸시켰다.

## 관측

| 장치 ID | Web 요청·장치 결과 | Rosy Cam에서 직접 본 몸체 | 판정 |
|---|---|---|---|
| `rosy_26` (`rosy-pinky-9dfk`) | 요청 `58c3aba848b7af4e` 수락, 장치 `done` | 화면 왼쪽 위 몸체(중심 약 x=130, y=170)의 후면 녹색·파란색 변화. 왼쪽 아래 몸체는 같은 구간에서 변하지 않음 | 현재 배치의 몸체 대조 확인 |
| `rosy_60` (`rosy-pinky-8kcn`) | 요청 `b3102100e354a95e` 수락, 장치 `done` (2026-10-08 17:54:41 UTC) | 화면 왼쪽 아래 몸체(중심 약 x=185, y=540)의 후면 빨간색이 17:54:38.565–17:54:40.053 UTC에 켜졌다가 꺼짐. 왼쪽 위 몸체는 변하지 않음 | 현재 배치의 몸체 대조 확인 |

`rosy_60` 영상은 시험 전 프레임(17:54:31.964 UTC)과 점등 프레임(17:54:38.565 UTC)을 비교했다. 밝은 유색 픽셀 수는 아래 몸체 ROI에서 9→23, 위 ROI에서 10→10이었다. 수치 단독 판정이 아니라 두 프레임을 직접 시각 검토했다. `rosy_26`의 영상도 점등 프레임을 직접 확인했다.

원본은 공개 저장소에 넣지 않고 `X:/DevTemp/`에 보관했다. 재확인용 SHA-256:

| 원본 | SHA-256 |
|---|---|
| `rosy26-lamp-test.webm` | sha256: `B30972AC8C9F748C2FE7327D9933312483A04637667F74DF583EF590BBD289F1` |
| `rosy26-lamp-16_5.png` | sha256: `B4B9B8506299BE68081528A147B935BF0EC19985B0D6C22D3AA2A6763561B810` |
| `rosy60-capture-frame0.png` | sha256: `E89705A685151CF1E60265080C3240209215A2FF9E8AF49832A1D60A327A3034` |
| `rosy60-capture-frame22.png` | sha256: `9445A7F054897D7F47408621610F857C5AE682A30EDBC52B6FB011D8EBE169A4` |

## 판정 한계

이 기록은 2026-10-09의 주차 위치에서 장치 ID와 화면 속 몸체를 연결한다(D-537). 카메라의 자동 named track은 0/0이고, Fleet 연결은 이전 설치물의 identity 조회 429로 0/2–2/2 사이를 오갔다(D-533). LCD 화면 내용은 카메라에서 보이지 않았다. 지도 localization, 이동 구역 수용, Web 이동, 두 로봇의 물리 주행은 이 회차에서 확인하지 않았다. 몸체나 카메라를 옮긴 뒤에는 다시 대조해야 한다.

## 역할별 구현 시험

- 대상: `ebba1acda` (D-537과 설치·정비 화면 구현을 포함한 `main` 병합 커밋).
- 모델 PC `rosy@100.98.162.71`의 격리된 소스와 Chromium에서 `ROSY_RUN_BROWSER_TESTS=1`로 `middleware/ui/robot/test/test_remaining_workflows_browser.py` 실행: 8 passed, exit 0, `known_failures.py` NEW 0. 원격 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-09--031749--physical-id-proof--138376/logs/browser-run.txt`에 보관.
- 현장 PC의 Fleet·Rosy Cam 영상과 각 Pinky의 하드웨어 시험 결과는 위 물리 대조 증거다. 새 설치·정비 화면 버튼은 로봇 설치본에 아직 배포되지 않았다.
## 2026-10-09 이동 전 재확인

- `rosy_60` Web의 전방 영상은 일시 409 뒤 다시 320×240, 약 0.4초 나이의 프레임으로 수신됐다. 천장 카메라는 약 2.7 fps이며 몸체는 왼쪽 아래에 그대로 보였다.
- 같은 시점 CORE는 `IDLE`, 속도 0, E-Stop `false`였지만 `/api/v1/robot/state`의 `evidence.safety.evidence`는 `disconnected`였다. LiDAR 최소값은 전방 −30…0° 0.491 m, 0…30° 0.257 m, 오른쪽 30…90° 0.111 m였다. 천장 영상의 몸체 주변에 선과 장비가 있어 짧은 주행의 바퀴 경로도 확정하지 못했다.
- D-522의 이동 전 조건을 충족했다고 판정할 수 없어 MANUAL 전환과 속도 명령을 보내지 않았다. 다른 로봇 `rosy_26`도 Fleet에서 `EnrollmentTlsError`로 연결이 불안정하고 named track은 0/0이다. 두 로봇의 실제 이동은 미시험이다.

## 착지 선택 시험의 기준선 비교

- `ea7f7a925` 전체 소스 스냅샷을 모델 PC에서 `tools/land.py --dry-run --tests auto` 선택 목록으로 실행: 1,118 passed, 12 skipped, 16 failed. 원본 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-09--031749--physical-id-proof--138376/logs/affected-run.txt`, 호스트·SHA·종료 코드는 같은 폴더의 `affected-verification.txt`다.
- 브라우저 실패 9건은 같은 모델 PC의 깨끗한 `main` 스냅샷 `fda0abfff`에서 모두 재현됐다(7건은 UI 묶음, 로그인 2건은 전체 의존 소스를 보충한 뒤 재현). 기준선 로그는 `main-browser-baseline.txt`와 모델 PC의 `entry-baseline.txt`다. 새 램프 패널의 집중 브라우저 시험은 위 8건 통과다.
- 나머지 7건은 이 토픽 밖의 원인 또는 시험 포장에 묶인다: 임시 실행 스크립트가 소스 루트에 있어 폴더 구조 검사 1건, `.git` 없는 tar 스냅샷이라 Git 속성·비밀 파일 검사 2건, 원본 `main`에도 있는 face 크기·lane literal 검사 각 1건, 다른 세션 선점 D-535·D-536이 미착지라 ADR 연속성 검사 2건. 이 설명은 전체 선택 시험의 통과 판정이 아니다.

## 2026-10-09 04:18 KST 읽기 재확인

- 현장 PC `robttt-15Z95N-GP7QL`의 `rosy-site-stack.service`는 active이며 Fleet·Vision 컨테이너는 실행 중이었다. 설치 이미지 revision은 `ed006ce92cc4832619dc96d4d0e00f779b439ec9`였다.
- 현장 PC에서 각 로봇의 사이트 CA와 TLS 호스트명 검증을 적용한 `GET /api/v1/auth/connection`은 `rosy-pinky-9dfk.local` → `paired`, `rosy_26`, HTTPS, HTTP 200; `rosy-pinky-8kcn.local` → `paired`, `rosy_60`, HTTPS, HTTP 200을 반환했다. 이 응답은 네트워크·인증서·논리 ID 확인이지 Rosy Cam 속 몸체의 현재 위치 확인은 아니다.
- `rosy_60`의 인증 없는 `GET /api/v1/robot/state`는 401이었다. 현장 PC SSH 계정에서 서비스 viewer·operator 토큰을 읽을 수 없어 인증된 현재 안전 상태, LCD 픽셀과 이동 경로는 이 재확인에서 판정하지 않았다.
