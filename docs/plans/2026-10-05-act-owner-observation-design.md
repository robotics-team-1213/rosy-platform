# ACT 입력과 OMX owner 관측 연결

기존 ACT 추론과 native owner 실행은 별도 증거다. native 후보 fixture를 실제
모델 출력으로 바꾸어 부르지 않는다. 이번 private 학습 adapter는 명시적으로
주입된 기존 session·ACTInference·원 RGB capture 사이의 입력 연결을 구현한다.

추론기를 execution-local 기본 driver에 넣으면 torch 의존성과 운영 활성화가
섞인다. 새 issuer나 scheduler를 만들면 기존 승인 경계를 우회할 수 있다.
학습에서 owner 내부를 직접 import하는 초기 구현은 tracked D-427/D-430 검사
2개에서 실패했다. 위반 예외를 만들지 않고 공통 DTO와 명시적 owner 입력 포트로
의존성을 뒤집는다. 실제 후보 구성은 isolated caller에 두며 운영 scheduler는 별도다.

- stdlib 계약 wheel의 기존 InferenceObservation/InferenceResult DTO를 한 곳에서 정의한다.
- owner capture_inference_input은 원 CameraSnapshot·RGB bytes·크기·SHA를 검사한다.
- 기존 owner 잠금 안에서 정책·lease·guarded joint와 camera를 함께 고정한다.
- 순수 학습 infer_captured는 같은 caller clock과 policy revision의 DTO로 추론한다.
- isolated caller는 잠금 밖 추론·post-lease/policy 검사·PolicyCandidate 구성을 담당한다.
- 큐의 원 source·생성 시각은 보존한다. 원 관측을 재전달하지 않는다.
- 제출은 기존 session.submit의 현재 권한·시계·source·최종 fence 검사에 맡긴다.

학습 함수는 명령을 보내거나 owner HOLD·추론 큐를 해제하지 않는다. hash 일치는
입력 무결성이며 trusted capture 발행자·설치 승인·승격을 만들지 않는다.
거절된 연구 artifact에서 임의 InstallBinding을 만들면 운영 승인이 되지 않는다.

검증은 원 RGB/시각 바꿔치기, 추론 중 권한·lease·모델 변경, 만료된 큐 provenance,
clock 불일치, 기본 disabled owner를 포함한다. 실제 CPU 계산 시험도 합성 모델과
관측을 사용하므로 실제 학습 품질·ROS dispatch·장치 과제 성공과 구별한다.
실제 학습 모델→승인된 capture→동일 native goal→Episode/Fleet 증거는 후속이다.
