# 차선 이탈 진단 기록 경로 검증

## 범위와 결과

사용자가 보고한 직선 흰 경계선 침범은 실제 주행 실패로 남는다. 사용자는 정지를 확인했다. 이번 검증은 기존 녹화기와 PC 변환 경로로 source-frame 경계·목표점을 보존하는지 확인한 것이다. 당시 이탈 원인 규명, 주행 수정, 새 소스의 장치 설치 및 FIELD 수용은 미완료다.

## 소스 변경과 검증

- Pilot raw 녹화에도 기존 `line/keep_debug`를 포함한다. annotated 녹화에서 중복 토픽을 제거한다. raw/annotated 영상의 annotation_origin, 저장 한도·복구·권한·정지 계약은 유지한다.
- MCAP 변환과 프레임 추출에서 keep debug를 이미지 header stamp로 연결한다. 기존 1us 허용 오차와 0.5s 수신 범위를 재사용한다. 늦게 도착한 다른 프레임의 진단, 누락된 stamp는 해당 프레임의 증거로 채우지 않는다.
- 진단은 side evidence이며 승인된 학습 마스크가 아니다. D-356 snapshot 녹화의 SIDE_TOPICS는 변경하지 않는다.
- RED: raw 진단 누락, 변환 토픽 누락 및 실제 MCAP 보존 실패를 확인했다. MCAP 테스트 의존성은 X 드라이브 전용 venv에 설치했다.
- 관련 회귀: **206 PASS**, known_failures **0 NEW**. 독립 리뷰: **87 PASS**, **0 NEW**, 소스 머지 차단 문제 없음. 테스트 로그는 `X:/DevTemp/lane-evidence-20261005/related-final.txt`와 `X:/DevTemp/lane-evidence-review-20261005/tests-green.txt`다.

## 실제 장치 정지 녹화

2026-10-05 11:01:53 UTC에 시작한 작업에서 기존 설치 recorder의 annotated 옵션을 사용했다. CORE의 IDLE·line-follow OFF·선속도/각속도 0을 확인한 뒤 녹화만 요청했다. 추가 주행 명령·hold 갱신·runtime 설정 변경·source hotpatch는 없었다.

- 녹화 시작 HTTP 201, 종료 HTTP 200, 자체 인증 세션 logout HTTP 204.
- 저장 세션 `20261005T110158Z_rosy_26`, manifest 길이 19.799s, archive 3,457,024 bytes. 내려받은 세 파일을 manifest SHA256으로 검증했다.
- 원본 카메라 **149프레임**, 변환 및 직접 추출 모두 **149개 진단 연결**. stamp_ns를 변환이 추가하는 차이를 제외하고 프레임별 진단 payload가 동일했다.
- 149개 진단 모두 `strategy=left_only`, `paint_source_used=threshold`. 이 정지 영상의 선택 결과이며 이전 주행 실패의 원인으로 단정하지 않는다.
- 프레임에 연결된 최종 명령의 nonzero 개수 **0**. 영상 변환의 moving 개수 **0**. CORE 상태 표본 12개도 정지였다.
- 확인 당시 CORE PID 13305, camera PID 13355, 두 서비스 active. 새 recorder 소스를 배포했다는 증거는 아니다.

원본·영상·프레임·private 인증 정보는 git에 넣지 않았다. 증거 위치는 `X:/DevTemp/lane-evidence-20261005/`의 `stationary-recording.json`, `fetch-verified.json`, `capture-analysis.json`, `recordings/`, `video/`, `frames/`다. 변환 sidecar SHA256은 `42f9553b2e433aa439dc81912efa676d3e31050db4ed512bb17fb0c4fb93ded7`이다. 재생은 카메라·명령의 정렬 확인이며 폐루프 주행 합격이 아니다.

## 남은 작업

정상 signed release로 새 raw recorder를 설치하고 설치 readback을 확인해야 한다. 다음 승인된 주행은 녹화 시작 확인 후 진행하고, 경계선 침범 구간을 독립 검토한 뒤 인식·목표점·명령·실제 응답을 비교한다. 승인 마스크 없이 모델을 새로 학습하거나 threshold/gain을 임의 조정해 이번 실패가 해결됐다고 주장하지 않는다.
