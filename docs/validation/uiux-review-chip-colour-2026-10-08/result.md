# 학습 검수 클래스 아이콘 색상 계약 · LOCAL

판정: **G1 원시 색상 회귀 수정 확인 / 학습 검수 표면 전체 HOLD**.

## 발견과 변경

- 공유 `main` `587b343064de277cc31e6132e136af1a9913221b`에서 D-153 G1 관련 네 시험 파일은 **80 passed, 1 failed**였다. 실패는 `pinky-review` 객체 빠른 클래스 선택 아이콘에 직접 쓴 `rgb(` 표현 한 줄이다. 같은 앱의 캔버스·픽셀 클래스 색상은 이미 검증된 `[r,g,b]`를 16진수 CSS 색으로 표현한다.
- 객체 아이콘도 같은 표현으로 바꿨다. 클래스 이름·색 값·선택/저장 동작은 그대로이며, 서버의 `class_sets.from_data_yaml()`가 색을 0–255 정수 세 개로 검사한다. 사용자에게 보이는 아이콘 색은 브라우저 시험에서 `rgb(12, 34, 56)`으로 확인했다.

## 검증

- 변경 브랜치의 G1 네 파일: **81 passed**, `known_failures.py` **0 NEW**. 색상 있는 사용자 클래스 세트의 선택·저장 브라우저 시험: **1 passed**, **0 NEW**.
- `rosy-pinky-review` 절차로 운영 상태가 아닌 X: 복사본의 357장 검수 자료를 열어 객체·객체 대기·픽셀·자료 등록·학습 목록을 데스크톱 1440×900과 전화 390×844에서 각각 촬영했다. 스모크는 오류·가로 넘침 없이 **OK**였으며 승인·제외를 보내지 않았다.
- 원본과 로그: `X:\DevTemp\projects\rosy-platform\2026-10-08--180942--ui-commercial-readiness--d97f93\`의 `evidence\review-smoke\` 및 `logs\g1-main.txt`, `g1-fixed.txt`, `review-class-browser.txt`, `review-smoke.txt`. 객체 화면 SHA-256: `desktop-objects.png` `ff47f4e6a8ae08cf9ddb558506ce7371d724158410605821302cfb02898a9fe3`; `phone-objects.png` `26711807cac7d1ae532d22cfd111af5ba361edb2bb5ca4543e5b12c744df7702`.

## 별도 사용성 공백

390×844 객체 검수 첫 화면에는 사진 목록·상태·이동·도구가 보이지만 원본 사진은 화면 아래다. 실제 검수 과업의 핵심 근거가 첫 화면에 없는 구조다. 이 색상 계약 수정으로 해결됐다고 계산하지 않는다. 검수자 과업의 첫 화면 위계, 선언 상태별 G2, 실사용 G3, 설치/배포는 여전히 **HOLD**다.
