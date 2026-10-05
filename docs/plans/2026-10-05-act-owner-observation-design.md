# ACT 입력과 OMX owner 관측 연결

기존 ACT 추론과 native owner 실행은 별도 증거다. native 후보 fixture를 실제
모델 출력으로 바꾸어 부르지 않는다. 이번 private 학습 adapter는 명시적으로
주입된 기존 session·ACTInference·원 RGB capture 사이의 입력 연결을 구현한다.

추론기를 execution-local 기본 driver에 넣으면 torch 의존성과 운영 활성화가
섞인다. 새 issuer나 scheduler를 만들면 기존 승인 경계를 우회할 수 있다.
따라서 학습 연구 경로에서 exact input을 구성하고 후보만 반환한다.

- CapturedRGB는 원 CameraSnapshot과 RGB bytes를 한 번 복사하고 크기·SHA를 검사한다.
- 기존 owner 잠금 안에서 정책·lease·guarded joint와 camera를 함께 고정한다.
- engine과 owner는 동일 clock 객체, 정확히 같은 정책 metadata를 사용한다.
- 추론은 잠금 밖에서 실행해 관측과 watchdog을 막지 않는다. 관측을 재전달하지 않는다.
- 추론 후 lease 또는 설치 정책이 바뀌면 거절한다. 큐의 원 source·생성 시각은 보존한다.
- 반환 후보의 실제 제출은 기존 session.submit의 현재 권한·시계·source·최종 fence 검사에 맡긴다.

adapter는 명령을 보내거나 owner HOLD·추론 큐를 해제하지 않는다. hash 일치는
입력 무결성이며 trusted capture 발행자·설치 승인·승격을 만들지 않는다.
거절된 연구 artifact에서 임의 InstallBinding을 만들면 운영 승인이 되지 않는다.

검증은 원 RGB/시각 바꿔치기, 추론 중 권한·lease·모델 변경, 만료된 큐 provenance,
clock 불일치, 기본 disabled owner를 포함한다. 실제 CPU 계산 시험도 합성 모델과
관측을 사용하므로 실제 학습 품질·ROS dispatch·장치 과제 성공과 구별한다.
실제 학습 모델→승인된 capture→동일 native goal→Episode/Fleet 증거는 후속이다.
