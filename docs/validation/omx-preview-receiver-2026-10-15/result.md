# OMX native preview 수신기 비교 — 2026-10-15

이 기록은 **30초 비교와 관측된 기본 수신기 저하**다. 30분 연속 수용 결과가 아니다.
새 카메라 source/서비스 배포나 팔 명령은 없었다. 기존 native Lyrical preview와
고정 camera source `dbe5db55b7`을 사용했다. Jazzy 실물 제어 수용으로 확장하지 않는다.

## 관측

- 두 카메라 unit은 오전 11:50 이후 같은 PID·설정으로 active, NRestarts=0이었다.
  producer의 private env에는 아래 Fast DDS 값이 이미 있었다. 호스트 load는 낮았다.
- 오후의 기본 수신기 첫 150초: top 737장(4.913 FPS), front 287장(1.913 FPS),
  최대 간격 각각 2.804/4.807초였다. 관측된 메시지 자체의 stale/nonadvancing은 0이었다.
  이는 메시지가 없는 구간이 없다는 뜻이 아니다.
- 동시에 publisher와 같은 transport 설정으로 별도 수신기를 30.082초 실행했다.
  front 300장, top 299장, 최대 간격 0.103844/0.106549초였다.
  그 비교 프로세스는 exit 0으로 끝났다. 두 수신기 모두 같은 raw Image topic,
  sensor-data QoS, 640×480 bgr8을 사용했다.
- 조건을 맞춘 수신기와 기본 수신기를 각각 30분 계측하는 후속 작업은 별도로 시작했다.
  이 문서에 미종료 작업을 성공으로 기록하지 않는다. 최종 결과는 별도 증거로 남긴다.

## 재현 조건과 판단

수신 프로세스가 ROS를 초기화하기 전에, 해당 preview 프로세스에만 다음을 적용했다.

```bash
export FASTDDS_BUILTIN_TRANSPORTS='DEFAULT?max_msg_size=60KB&sockets_size=2MB&non_blocking=true'
```

ROS 환경과 workcell domain은 현장 선택값을 사용한다. 명령의 `&`를 셸 제어 문자로
해석하지 않게 따옴표를 유지한다. 전체 PC 설정·커널·방화벽·다른 ROS 노드에는 적용하지 않았다.

현재 증거는 **수신기 전송 설정이 수신 품질에 영향을 준다**는 것이다. USB 캡처 속도 저하나
DDS 내부의 특정 원인을 독립적으로 확정하지 않는다. 앞선 30초 기본 수신기 성공은 그때의
표본이며, 이번 저하를 무효로 만들지 않는다. 실제 소비자의 연속 수신을 따로 검사해야 한다.

host-receive stamp는 노출 시각이 아니다. CameraInfo·hand-eye/TCP·실물 팔 profile·정지 수용,
지속 AI 추론과 Fleet의 사실 소비는 여전히 이 비교로 입증되지 않는다. 하드웨어 명령은 0회다.

원문은 비공개 실행 세션의 `logs/omx-endurance-low-rate-diagnosis.txt`,
`logs/omx-endurance-matched-receiver.txt`, `logs/omx-stream-endurance-30min.txt`에 있다.
실제 장치 식별자·호스트 경로는 공개 문서에 옮기지 않는다.
