# OMX native 파지 구간

V-021의 학습센터 범위를 구현한다. 기준 main은 `58db88b7a233c7f081b4630d78ceeba6f7ccdbd8`이며 이전 조사 SHA `45b2bfe`와 대상 OMX 경로 차이는 없다. 사용자가 2026-10-21 한 개의 추가 워크트리 생성을 승인했다. 브랜치는 `feat/hybrid-il-data`다.

1. 원본 report/hash/session/cycle를 묶은 정수 프레임 구간과 사람 결과 검수의 실패 테스트를 먼저 커밋하고 원격 실행한다.
2. 원본을 재검증한 뒤 관측·명령·카메라를 같은 프레임에서 복사하고, 각 구간을 새 child Episode로 내보낸다. 원본 provenance와 새 frame index의 계보를 구분한다.
3. 기존 ACT native split receipt 검증에 구간 receipt를 연결한다. native 단위와 SIM rad 데이터는 분리하고 train-only 통계를 유지한다.
4. 등록된 OMX 자료의 원본 프레임 확인·수동 경계·명시 결과·검수 저장·선택 JSON 내려받기를 화면에 연결한다. 기존 token/origin/account 권한을 유지하고 원본 decisions를 수정하지 않는다.
5. 커밋 HEAD의 OMX curation/training 및 HTTP·브라우저 시험을 원격 runner로 실행하고 known_failures와 비교한다. LeRobot readback skip과 불통 호스트는 검증 완료로 계산하지 않는다. push·merge·장치 실행은 범위 밖이다.

실제 데이터 절감·정책 학습·장치 결과 수용은 별도 실험이다. 실패·미판정·개입은 보존하며 성공 정책에 자동 편입하지 않는다.

원격 affected 시험에서 signed model-PC importer의 복사된 소스 closure가 새 OMX 의존성을 포함해야 함을 확인했다. 관련 `deploy/site/model_code_layout.py`와 source-proof 시험을 소유 범위에 추가했다. 15개를 넘는 변경은 하나의 구간 계약·검수·학습과 그 signed archive 전달을 함께 검증하는 결합 범위이며 독립 기능을 덧붙이지 않는다. 실제 배포는 수행하지 않는다.
