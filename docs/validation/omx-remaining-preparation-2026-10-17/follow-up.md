# 추가 준비 후속 — Fleet 환경 설치와 실제 센서 부재

2026-10-17, [최초 접속 실패 기록](result.md) 이후의 별도 관측이다. 이전 실패 기록은 유지한다.
사용자는 모델/AI PC가 켜져 있어야 한다고 답했다. 전원 차단을 원인으로 단정하지 않았다.
AI/Fleet에는 재접속됐고 모델 PC는 추가 두 차례 banner exchange 시간 초과 뒤 세 번째 시도에서 복구됐다.

## Fleet에서 실제 완료한 준비

private 재개 묶음의 `run-preparation.py --role fleet`가 exit0이었다.
원격 `~/rosy-test/omx-collection-b88eee5f18/readiness-90b7a2b85d2c/receipt.json`에 결과를 보존했다.
배치된293개 원본 hash가 전후 일치했다. 기존 카메라 env의 실제 ROS domain/setup과 기존 native overlay,
private profile/teacher/acceptance, 새 OUTPUT, episodes1을 사용해 수집 env를 새로 만들었다.
설정이 바뀌는 경합을 피하도록 비활성 profile과 만료된 acceptance의 별도 사본으로 launcher를 검사했다.
실제 ROS setup/overlay를 거친 launcher가 exit2와 blocked.json을 남겼고 hardware backend를 만들지 않았다.
수집 unit inactive와 실제 수집 OUTPUT 미생성도 확인했다. 실제 시연·토크/Action 명령은0개다.

passive6초 ROS 구독에서 top/front 새 frame은 각각0개였다. graph에 trajectory Action이 없고
controller 프로세스도 관측하지 못했다. controller를 시작하지 않았다.
기존 localhost viewer의 마지막 영상은 약17872초 전으로 fresh=false였다.
환경 receipt는 INSUFFICIENT, 양쪽 STALE, photometric_ready=false, motion_admitted=false였다.
과거 UNDEREXPOSED 등의 condition을 현재 방의 조도로 해석하지 않았다.

추가로 실제 top/front camera service 인스턴스를 확인했다. 둘 다 active/running이지만
설정된 stable by-id 장치가 존재하지 않았다. journal에는 selected camera is unavailable이 반복됐다.
현재 by-id에는 내장 LG camera만 있었다. 장치 이름 변경/권한 오류를 검증 없이 원인으로 단정하지 않았고
다른 카메라로 자동 치환하지 않았다. 기존 producer의 재연결 대기는 유지했다.
camera view/readiness service도 active였다. 새 센서 입력이 없으면 수집을 허용하지 않는 실제 부정 사례다.
두 외장 카메라가 OS에 다시 열거되는 것은 현장 연결 확인이 필요하다.

실제 설치된 두 producer source는 b88eee5f18의 `omx_adapter/camera_source.py`와 hash가 같았다.
Camera source SHA-256: `caaa439c383eb9ed33ee8dc3dbc3637bbc82b9147b1de5ec8bfdf4c78cbcf1e9`.
이 source는 같은 stable by-id 경로를1초 간격으로 다시 확인하고, 읽기 실패 시 capture를 닫아 다시 연다.
기존 `test_camera_source.py`를 원격 모델 PC에서7개 통과했다. NEW0/known0/flaky0이며
외부 scratch `camera-reconnect-existing-source/run-1.txt`에 보존했다.
현재 실제 장치가 없어 실제 USB 재연결·새 영상 회복까지 시험한 것은 아니다.

원격 진단은 `camera-diagnostic-1792213907469968926/`과
`camera-instances-1792213959510491268.json`에도 보존했다. 둘 다 같은 source snapshot 디렉터리 아래다.

## 모델 PC와 원격 검사

모델 PC의 추가 두 시도는 private 묶음의 attempt-model 디렉터리에 stdout/stderr/result를 남겼다.
비공개 기존 LAN 기록의 SSH 주소도 Fleet에서 응답하지 않았고 neighbour 확인은 FAILED였다.
이는 현재 LAN 주소나 전원 상태의 재검증이 아니다. 네트워크/전원 원인은 미확정이며 재등록·키 교체·
네트워크 설정 변경·임의 wake를 수행하지 않았다.

이후 Tailscale online과 실제 SSH 복구를 확인했고 `run-preparation.py --role model`의 세 번째
추가 시도가 exit0이었다. 새 `model-preparation-*/receipt.json`에 source b88eee5f18 전후 무결성,
prepare/train 실제 진입점 도움말 성공, 수신/receipt 저장 경로, free195672408064bytes를 기록했다.
receipt의 recorded_ns는1792214060981643130이다. 개발 PC 원본 로그는
`private/omx-next-day-preparation-20261017/attempt-model-b89110fa9e84/`에 있다.
이 단계는 실제 학습을 다시 실행한 검사가 아니며 실제 데이터는0회다. 네트워크 복구 원인은 미확정이다.

`0dc0fb7067`의 문서 계약 원격 검사는 재시도 도중 복구된 AI PC에서142개 통과했다.
대상은 network_topology_contracts, harness_contracts, document_placement, folder_layout이며 skip0이다.
로그는 외부 scratch `remaining-preparation-docs/run-1.txt`. NEW0/known0/flaky0, lint0error/32warning.
노트북 pytest는 실행하지 않았다. 이 검사는 모델 PC나 외장 카메라 수용이 아니다.

## 준비 스크립트 검토

독립 리뷰에서 모델 스크립트가 source 검증 전에 launcher를 호출하는 순서와 고정 로그 경로를 지적했다.
기준 revision/archive·전체 source hash·예상 interpreter/pipeline을 가리키는 wrapper bytes를 실행 전에
검증하고, 새 UUID 경로에 help stdout/stderr를 보존하며 실행 뒤 원본을 재검사하도록 수정했다.
HF offline 환경을 명시했고 shell/Python 문법 검사를 다시 통과했다. 최종 독립 리뷰 material finding0건.
수정 뒤 모델에서 위 help/소스/공간 점검은 실제 실행했다. 학습이나 장치 실행을 시작하지 않았다.
private 묶음의 최종 파일은 다음 hash로 식별한다.

- check-collection-model-ready.sh SHA-256: `508f8c0aa3d5ce37e456d806c7e2b12fb0ca95741d2695ab81e48e576c54ebff`.
- finish-collection-preparation.sh SHA-256: `f9f3228c37efc55a3d6745efa20e270383dfdcb8888fcf77339d48d8074081cc`.
- run-preparation.py SHA-256: `f33bda836e26d982b4bc52957cbaeb3101854a0f0267eff2c8e2747db9c61444`.

내일 남은 것은 외장 카메라 재연결 확인, 실측/물리 정지·시야·하중 검수와
유효한 profile/teacher/acceptance, 첫 실제 수집이다. 원격 실행 환경 준비의 완료와 이 항목을 구분한다.
