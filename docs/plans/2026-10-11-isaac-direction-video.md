# Isaac 한 대 방향별 완주와 실제 화면 녹화

사용자는 궤적 재생에 더해 실제 Isaac 화면과 여러 시작 방향의 주행 검증을 요청했다. D-638의 native 한 대 진단 범위 안에서 기존 학습 정책을 고정하여 재평가한다. 운영 CORE/Fleet 연결과 두 대 신호 시험은 이 검사에 포함하지 않는다.

실행기·task·recorder는 D-427의 기존 `tools/sim/isaac/` 도구 소유에 둔다. `learning/envs/isaac/`는 SDK helper/assets/회귀를 유지하고 learning root에서 CORE 내부를 직접 import하지 않는다.

1. 최신 main을 topic에 통합하고 기존 전체 학습 재시험 R8의 종료와 source hash를 확인한다.
2. 저장 정책의 gains·state 범위·유한 Q·실제 updates를 검증하는 restore와 실제 renderer frame을 ffmpeg에 보내는 최소 녹화를 시험 먼저 구현한다. 외부 새 의존성은 추가하지 않는다.
3. 기존 runner의 기본 학습은 유지한다. 별도 `--policy-file`은 학습 없이 seed 707/808/909/1001, 경로 시작 방향 대비 0/+90/180/-90도의 고정 정책 평가만 실행한다. 기존 CORE 최종 port·Drive·물리 stop/reset 판정을 그대로 쓴다.
4. `--record-video`로 headless Isaac 상공 카메라의 RGBA를 직접 저장한다. 0.2 simulation 초마다 실제 프레임을 기록하고 25fps로 인코딩한다(5배속, 위치 보간 없음). 프레임별 renderer 번호·시각·physics pose를 JSONL로 남긴다. empty/stale frame 및 encoder 실패를 성공으로 처리하지 않는다.
5. 실제 영상 첫·중간·최종 화면, raw trace의 ordered progress·정렬·완주·물리 stop, 정책 불변·hash를 함께 확인한다. 어느 방향이 실패하면 해당 실패를 기록하고 성공 방향으로 대신하지 않는다.
6. 결과를 `private/isaac/` 일지·결과에 추가하고 공개 검증 문서·진행 상태를 갱신한다. 관련 원격 회귀·lint·land·pre-push를 통과한 뒤 사용자가 승인한 main 병합과 원격 push를 수행한다.

맵은 `map_v2_fleet/260919 MAP FILE.STL` 원본과 기존 curved generator를 유지한다. 렌더 카메라·조명은 관측용이며 로봇 형상·질량·Drive/CORE 로직이나 물리 판정을 변경하지 않는다. 실제 RGB 화면은 지도 pose를 그린 replay와 별도로 표기한다.
