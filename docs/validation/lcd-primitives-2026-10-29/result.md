# LCD 기본 그리기 부품 분리

2026-10-29 · `refactor/lcd-display-primitives` · 기준 `1bae8682470c` · source `51bfc31b763a` · 최종 시험 `75d706130adf`.

info_screen.py의 font/폭 fitting·유효 측정값·hold duration·QR·패널 RGB565 packing을 lcd_primitives.py로 옮겼다. 카드 배치 파일은676→560줄, 부품은129줄이다. 기존 import 이름은 info_screen에서 re-export하며 호출자를 바꾸지 않는다. palette tuple과 surfaces.yaml의 token_copy 경로는 유지한다. QR 흑백은 기존 token-exempt 매체 값이다. 폰트 제약 시험은 실제 정의 파일을 검사하고676줄 ratchet을 제거해600줄 한도로 복귀시켰다.

모든24 function/class AST가 같고 이동한7개 함수도 본문 변경이 없다. 기본 wake4+drive3 PNG는 baseline과7/7 bytes/hash가 같다. lcd_primitives는 info_screen을 역참조하지 않으므로 새 import cycle이 없다. 기존 clipping P2는 이 분리에서 고치지 않았으며 별도 uiux/lcd-card-consistency가 소유한다.

원본은 `C:/DevTemp/rosy-ui-standardization/`이다. reports/captures manifests와 lcd-primitives-invariants.json으로 결합한다.

| SHA / 로그 | 실제 결과 |
|---|---|
| `51bfc31b76`, lcd-primitives-support/run-1.txt | 전체face+token parity/native export193 pass/6 skip/10 warnings·5subtests. capture opt-in2와 ROS linter3·native exporter opt-in1은 실행 통과로 세지 않음 |
| `75d706130a`, lcd-primitives-built/run-1.txt |3 pass/0 skip. 기존7장 캡처와 setuptools build_py→python -I cold import/packing |
| `75d706130a`, lcd-primitives-affected/run-1.txt | 공식 affected1307 pass/1 skip/45 warnings, NEW0. 선택된 source/계약의 범위이며 CI/FULL이 아님 |

통과 로그는 known_failures NEW0/known0/flaky0이다. 부분/전체/반복 결과를 합산하지 않는다. A가 독립 source 검토에서 새 P1/P2를 찾지 못했다. 기존 상태바 아래 clipping을 해결했다고 확대하지 않는다.

cold import 시험은 소스를 임시 package로 복사해 build_py 산출물을 만들고 저장소 밖 cwd의 python -I에서 그것을 import한다. info_screen과 lcd_primitives의 실제 파일 경로, 기본 카드 크기, RGB565 shape/dtype, rclpy 미import를 검사한다. 실제 colcon/릴리스 이미지 설치·ROS·SPI·장치·FIELD 증거가 아니다. 다음 overlay 분기 시험은 별도 수정 브랜치 기록에서 다룬다.

CE: 해당 없음 — 설치 배치 교훈을 cold import에 적용했고 AST/기존 픽셀·API 보존은 소스와 시험에서 복원된다. 장치·운영 장애 해결을 주장하지 않는다.
