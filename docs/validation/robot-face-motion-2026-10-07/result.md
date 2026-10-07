# D-504 로봇 얼굴 표정·애니메이션 LOCAL 확인

- 대상: `uiux/face-motion`, `rosy-face`의 기존 LCD 경로와 `emotion/*.gif` 여덟 종. 릴리스·장치 적용 전 브랜치 근거.
- 이전: GIF 1000×750·40 ms, `rosy-face`에서 매 두 번째 프레임만 읽고 10 fps(대기 5 fps)로 표시. 첫 프레임을 32×24로 축소하면 `basic`·`fun` 전경 차이 0.3%; `hello`는 공백.
- 변경: 320×240·20프레임·100 ms 루프, 첫 프레임부터 얼굴 표시. `basic/interest/happy/fun/bored`는 작은 실루엣에서 서로 최소 6% 차이. 얼굴별 눈·입 변화와 작은 위치 이동을 적용했다. 첫 프레임 여섯 종을 원본 크기에서 열어 형태를 점검했다.
- 호스트 시험: `python -m pytest test/test_rosy_face.py middleware/ui/face/test/test_face_assets.py middleware/ui/face/test/test_emotion_runtime.py middleware/ui/face/test/test_info_screen.py middleware/core/gateway/test/test_emotion_map.py contracts/foundation/test/test_face_screen.py -q -rfE -p no:cacheprovider` → 362 passed, 3 skipped. `python test/known_failures.py <run.txt>` → 0 new, 0 known. 원시 로그는 `X:\DevTemp\projects\rosy-platform\2026-10-07--203421--face-motion--11cd4d\logs\face-pytest.txt`.
- `python tools/harness/rosy_harness.py lint` → 0 errors, 22 기존 모듈 검증 시점 경고. ADR 본문·인덱스 형식 오류 없음.

## 장치 수용에 필요한 관찰

이 회차는 LCD 사진이나 사람이 1.5 m에서 읽은 결과를 얻지 못했다. 다음 릴리스 후보가 설치되면 실제 패널에서 정면·비스듬한 각도, 실내 밝음·어두움에 `basic/interest/happy/fun/bored`가 0.5초 안에 구별되는지 확인한다. 정상→수동→내비게이션→도킹→막힘의 얼굴 전환과 비상정지·CORE 중단의 카드 우선순위, 주행 카드 만료 후 얼굴 복귀를 관찰하고, 10/5 fps 끊김과 CPU·RSS를 기록해야 DEVICE 판정이 가능하다. FIELD 판정은 별도다.
