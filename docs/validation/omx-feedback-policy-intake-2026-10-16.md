# OMX source-age 수정 후 정책 연결 재검증 — 2026-10-16

[원본 시각 오류 재현](omx-feedback-source-age-2026-10-16.md)의 후속 실행이다.

최초 착지의 확대 시험에서 **3실패·1351통과·13skip**으로 merge가 중단됐다.
세 실패는 `test_policy_runtime_binding.py`가 생성자를 생략하고 runtime 메서드만
추출해 쓰면서 새 intake 초기화와 header를 제공하지 않은 fixture 오류였다.
실제 생성자 경로를 느슨하게 만들거나 무시 조건을 추가하지 않고 fixture를 수정했다.
별도의 실제 ROS policy publisher에도 원본 clock stamp를 넣었다.

- `3a09f5172`: 정책 runtime 연결 host 검사 **22통과**, NEW 0
- `de86b7a48`: 모델 PC Jazzy/Python 3.12에서 native runtime **8통과**, 정책 ROS
  transport **4통과**; 두 child suite를 실행하는 원격 wrapper **2통과**, skip 없음

두 번째 child는 기존 격리 domain 199 요구를 유지한다. 실제 ROS ActionServer로
정책 명령의 UUID/종단 사실과 권한 철회, parent episode/Fleet 연결을 검사한다.
이는 합성 SIM 정책 fixture이며 실제 모델 학습이나 물리 시연을 뜻하지 않는다.
첫 child는 domain 113이다. 두 domain 모두 localhost이며 장치·vendor launch는 없다.

원문 로그는 개발 PC 외부 `rosy-il-python312/state-policy-fixture-green/run-1.txt`와
`rosy-il-python312/state-native-policy-green/run-1.txt`에 있다.
독립 검토에서 source-age 구현의 material finding은 없었다.
