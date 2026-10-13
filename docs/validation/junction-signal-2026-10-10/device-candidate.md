# D-620 장치 빌드 후보

- 브랜치: `fix/junction-device`.
- 런타임 코드 검증 SHA: `e83d3038f9`.
- D-620 소스 `feat/junction-signal`에 이전 release 137의 두 수정도 포함했다:
  wall 없는 v2 drivable model의 floor gate 호환 및 현재 차체 내부 LiDAR 반사 제외.
  관련 원래 테스트도 같이 포함했다. 모델 슬롯 및 장치별 3초 횡단보도 설정은 장치 데이터다.
- AI PC 원격 합동 검증 **432 passed, 2 skipped**, known_failures **0 NEW**.
  `X:/DevTemp/junction-device-verify/run-1.txt`.
  skip에는 호스트의 선택적 ONNX 추론 의존성이 필요하다. 장치 추론 증거로 사용하지 않는다.
- 원본 D-620 API/설정/foundation/Fleet app/문서 계약은 **1095 passed**, 0 NEW.
- `ship.py --base 2026.10.10-137 --revision HEAD --dry-run`은 신규 CORE
  `junction/signal.py`가 추가돼 delta를 거절했다. Fleet 신규 파일 및 situation 파일도
  별도 배포 분류가 필요하다고 출력했다. unsigned 덮어쓰기로 이를 우회하지 않았다.
- dry-run의 오류 문자열은 release 138이 예약됐다고 했지만,
  `git ls-remote --tags origin refs/tags/payload-reserved-2026.10.10-138`은 비어 있었다.
  release 번호는 실제 전체 빌드 시 도구로 다시 예약한다.
- 필요한 다음 단계: 이 후보 브랜치를 원격에 push → native ARM64 payload build →
  ROS deb ABI 확인 → 오프라인 서명 → Fleet 이미지 build → 양쪽 설치/readback →
  현장 감독이 있는 교차로 시나리오 검증. Fleet/CORE 모두 준비된 뒤 명시적 시험 설정을 켠다.
- 사용자가 지금까지 명시한 Git 작업은 commit이다. 저장소 AGENTS 「같이 하는 깃」 6항은
  push를 별도 명시 요청 뒤에 하도록 정한다. `rosy-release-push`의 전체 빌드 경로도
  원격 브랜치에 있는 커밋을 ARM64 Actions가 빌드하므로 push 승인이 필요하다.
- 현재 signed artifact·새 기능 설치·교차로 실물 통과는 **미확인**이다.
