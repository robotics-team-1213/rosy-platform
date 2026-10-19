# OMX SIM 전용 시계 실행기 구현·검증 계획

기준: D-788. 실제 cross-clock 관측의 원인을 확정한 것으로 취급하지 않는다.

1. owner의 기존 provider 읽기 전후에 builtin steady bracket을 추가한다. 관측 실패에도
   provider 예외·횟수·guard·취소를 유지하는 원격 RED/GREEN과 독립 D-430 review를 남긴다.
2. SIM 전용 clock helper가 고정 SDK/API를 확인하고, feedback/Goal 전에 기존 자동
   TimeSource의 subscription·parameter callback·clock 연결을 정리한다. 명시적 source
   하나가 같은 owner clock을 갱신하고 두 use_sim_time을 고정한다.
3. clock node는 SingleThreadedExecutor, owner는 네 group의 별도 실행기를 쓴다.
   원격 회귀에서 이전 updater의 추가 쓰기 불가·막힌 owner 작업 중 clock 진행·초기화
   실패의 no-goal·bounded 정리를 검증한다. callback에는 I/O나 owner lock을 넣지 않는다.
4. 실제 publisher count/GID/QoS·진행·역행·thread health 기록을 preflight/종료에 남긴다.
   초기화는 단일 publisher와 신선한 clock 진행을 확인한 뒤에만 owner를 연다.
5. 고정 source를 SSH로 새 run에 배포하고 한 번만 시작한다. startup/topic/16개 독립
   placement 목표와 정리를 확인한다. HOLD면 frozen 결정과 bracket·intake·clock 관측을
   결속해 다음 원인을 구분하며, 같은 run이나 불명 Goal은 재전송하지 않는다.
6. 최종 affected 원격 검증과 로컬 병합을 수행한다. push·실물 수용·full G2·실제 학습은
   각각 따로 확인하며 본 계획의 성공으로 표시하지 않는다.
