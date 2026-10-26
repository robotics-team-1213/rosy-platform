# 로봇 상세 프로필과 하중 분석 연결

관제에서 로봇을 선택하면 실시간 모터 상태 다음에 저장된 주의사항, 특성 요약과 최근 분석이 나오고 그 아래에 기존 조작이 이어진다. Cell의 등록 팔에도 같은 프로필을 표시한다. 프로필 조회에 실패하면 조회 불가를 표시하며 공용 비상 정지는 기존 경로로 유지한다.

`설치 → 장치 정보`에서 설명 프로필을 저장하고 관측원 목록에서 해당 robot 또는 arm source를 직접 연결한다. 표시 이름이나 USB 식별값이 같아도 자동 연결하지 않는다. 주의사항은 계속 표시하고 고장 관찰·정비 내용은 작성자와 시각을 포함한 최근 100건으로 보존한다. 기록 추가는 실시간 고장 해제가 아니다. 이 데이터는 task SQLite와 같은 파일에 별도 테이블로 저장하므로 해당 DB 백업·복구에 함께 포함된다.

특성 JSON은 [하중 평가 계산기](../../../middleware/devices/omx/adapter/docs/load-aware-motion.md)의 문서 그대로 가져오고 내보낸다. 장치 ID는 프로필 ID와, owner는 등록 arm owner와 일치해야 한다. 가져온 파일 원문을 서버에 보내 중복 키·비유한 수·잘못된 측정 구간을 계산기와 같은 검증으로 거절한다. `measured`는 제출된 측정 기록이며 현장 수용·안전 승인이 아니다. 입력 중 다른 장치 선택과 poll은 초안을 덮어쓰지 않는다.

자동 분석 연결은 기존 CLI `watch`의 `--output` 파일을 아래 발행기에 명시한다. Workcell arm source와 전용 자격, 검증 가능한 HTTPS Fleet 인증서가 먼저 설정되어 있어야 한다. 자격은 환경변수로 전달하고 파일·문서·로그에 쓰지 않는다.

```sh
python -m deploy.robot.omx.load_report_bridge \
  --report /run/rosy/load-analysis.json \
  --fleet-url https://fleet.example \
  --device-id arm-one --source-id arm-observation-one \
  --token-env ROSY_ARM_OBSERVATION_TOKEN --ca-file /etc/rosy/fleet-ca.pem
```

`--once`는 파일 한 건만 발행한다. 기본은 바뀐 파일만 보내고 통신 오류는 같은 원본 시각으로 재시도한다. Fleet은 분석·관절 capture 시각으로 만료를 계산하므로 재시작·중복 전송이 오래된 관측을 새것으로 만들지 않는다. 재연결이나 특성 변경은 최근 분석을 무효화하며 과거 기록은 남긴다.

이 발행기는 관측을 전달한다. 모터 버스를 열거나 경로·속도·토크·정지·복구 명령을 실행하지 않는다. 실제 경로 실행은 기존 owner의 별도 수용과 현재 상태 검사를 거쳐야 한다. 장치 서비스 활성화와 물리 하중 검증은 이 구현 시험에 포함되지 않는다.
