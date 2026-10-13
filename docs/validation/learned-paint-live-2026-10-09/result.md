# 실기 learned paint가 사용되지 않는 구간과 10/7 녹화의 기하 공백

**판정: DEVICE 읽기 전용 진단, 주행 HOLD.** 2026-10-09 KST, 두 Pinky의 설치본 `2026.10.08-055`(source revision `e8efc5cb510c9a5c454b333d436a60857fb22a0e`)를 조사했다. SSH와 ROS 구독만 사용했고 주행 명령, 설정 변경, 녹화 시작, E-Stop 조작은 하지 않았다. 아래 로봇 이름은 공개 제품 식별자이며 접속 주소·계정·키는 기록하지 않는다.

## 원본 영상에서 재생이 막힌 위치

출처가 [207/207장 증명된 10/7 MCAP](../lane-1007-source-proof-2026-10-08/result.md)의 두 세션에 현재 `road_replay.py --recorded-ground --compare-boundary --max-frames 1`을 각각 실행했다. 둘 다 첫 장에서 `missing line/keep_debug`로 종료했다(비정상 종료 코드 1). 두 bag의 MCAP 채널 목록에는 `line/keep_debug`가 있으나 실제 메시지는 0건이었다. `CAMERA_LINE` 관측은 첫 세션 124건, 둘째 83건 있다. 채널 선언과 영상 관측만으로 그 프레임의 바닥 투영을 복원할 수 없다. 당시 카메라 모드는 기록되지 않았으므로 현재 로봇 설정을 10/7 당시 설정으로 소급하지 않는다.

## 현재 로봇에서 확인한 것

| 기기 | 현재 카메라 모드·기하 | 실시간 검증 |
|---|---|---|
| Pinky 9dfk (`rosy_26`) | `keep`, `NOMINAL` 바닥. 운영 override는 `paint_source: learned`, `learned_paint_every_n: 2`, `learned_paint_threads: 2` | [읽기 전용 probe](evidence/probe.py)에서 카메라 25장, `keep_debug` 25건 모두 영상 시각·투영값 있음. 그러나 `paint_source_used`는 **25/25 `denoise_fallback`**, 사용 모델 revision은 0건. 설치 모델은 정상 로드(`lane-seg-20261006-28e8454d`), 같은 실시간 카메라 한 장에서 독립 추론 337.4/332.9/327.7 ms(중앙값 332.9 ms). |
| Pinky 8kcn (`rosy_60`) | `line`, `PINKY` 바닥 | 4초 동안 `keep_debug` 0건. 현행 코드에서 `keep_debug`는 `keep` 분기에만 발행한다. 카메라 calibration/status는 두 기기 모두 조사 시 `mode=pinhole`, `active=false`, `pinhole_active=false`였다. |

9dfk의 `keep_debug` 토픽은 별도 6초 관찰에서 약 7.3–7.9 Hz였고, 조사 표본의 strategy는 `left_only`였다. 두 기기의 `/cmd_vel` 발행자 목록에는 각각 자신의 `core` 하나만 있었다. 이는 조사 순간의 그래프 readback이며 실제 주행 수용 증거는 아니다.

재현: 설치본의 ROS 환경을 불러오고 같은 ROS domain/RMW에서 `evidence/probe.py`를 표준입력으로 실행한다. 예를 들어 `python3 - --namespace /rosy_26 --pointer /var/lib/rosy/models/shadow --threads 2`에 파일을 pipe한다. probe는 ROS 메시지를 발행하지 않고 `line/keep_debug`와 raw `camera/front`를 구독한다. 모델을 별도 프로세스에서 로드해 3번 재추론하므로 실제 keeper worker의 내부 큐·지연을 직접 계측한 것은 아니다. 로봇에 파일을 남기지 않는다.

## 원인 가설과 처리 순서

현행 `LearnedPaintWorker.mask_for`는 모델 결과가 제출 후 `every_n` 프레임을 넘거나 `stale_s` 0.6초를 넘으면 버리고 `denoise_fallback`으로 간다. 8 Hz의 두 프레임은 약 250 ms인데 독립 추론 3회가 모두 328–337 ms였다. 결과가 만들어질 때 이미 프레임 나이 제한을 넘기는 것이 **25/25 fallback의 강한 원인 후보**다. 실제 worker 큐나 reset의 동시 관측은 없으므로 단일 원인으로 확정하지 않는다. 1스레드 465–475 ms, 3스레드 358–391 ms, 4스레드 365–406 ms의 짧은 비교에서 스레드 수를 늘리기만 해서는 이 구간을 해소하지 못했다.

안전상 `every_n`이나 `stale_s`만 늘려 오래된 마스크를 조향에 쓰지 않는다. 움직이는 로봇에서 0.3–0.5초 전 마스크는 경계와 어긋날 수 있다. 다음 후보는 (1) 더 빠른 모델·입력 크기를 **사람 검수 고정 평가 세트**에서 비교하고 Pi 동시 부하에서 deadline을 측정하거나, (2) odom 워프한 prior를 가림 구간의 후보로만 두고 현재 관측·벽/분기 증거와 충돌하면 STOP하는 것이다. 두 후보 모두 10/6·10/7 동일 물리 경계 ID 검수, 보정된 바닥, 재생·SIM·DEVICE 시험 없이 주행으로 승격하지 않는다. 현행 `denoise_fallback`과 CORE 단일 명령 경계는 유지한다.

기록된 10/7 화소와 현행 9dfk의 live 투영은 다른 날짜·기기 조건이다. live `NOMINAL` 투영을 옛 MCAP에 채워 넣어 `--recorded-ground`를 통과시키지 않는다.
