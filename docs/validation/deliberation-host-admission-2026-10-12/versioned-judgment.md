# 교체 가능한 판정 JSON과 독립 보정 구현 증거

Contract: D-681. 이 기록은 SOURCE·원격 논리 시험이며 운영 모델의 품질이나 장치 수용 증거가 아니다.

## 구현 경계

`ModelProfile`은 역할·정확한 모델 ID/revision·제공자·어댑터·schema·도메인·입력 형태·호출/시간/출력/비용 상한을 고정한다. `BoundProfile`은 현재 사건 digest에 묶이며 제공자 능력, 준비, 격리와 비용 검증이 일치해야 한다. Fleet에 모델 이름별 분기를 넣지 않는다.

v2 JSON은 사건·프로파일·전체 선택지의 확률 합·근거·부족 근거·반대 의견·다음 단계·성공 확인을 검증한다. 다음 단계는 기존 공통 catalog의 허용된 feedback 도구이며 성공 확인은 읽기 전용이다. 선언한 성공 조건은 실제 성공 receipt가 아니다. 기존 D-640 응답은 유지한다.

CLI와 로컬 제공자는 같은 v2 요청 생성기를 사용한다. 기존 GLM 연결은 아직 v2·검증 비용 admission이 없으므로 v2 호출 전에 거부한다. 새 parser를 추가한 것만으로 운영 활성화하지 않는다.

독립 보정은 학습 manifest, fit, 평가의 사건·세션·녹화 ID와 내용 SHA 중복을 거부한다. 검수한 데이터 SHA와 프로파일 전체 SHA-256을 artifact에 고정한다. 모델 ID뿐 아니라 역할·어댑터·시간·예산을 변경해도 이전 보정을 재사용하지 못한다. 확률 구간에 fit 근거가 없으면 HOLD이며 검수한 품질·지연 한계가 없으면 HOLD다.

평가 보고서는 Brier, ECE, 지연, 금지 오류와 구간별 정확도의 점별 단측 Wilson 하한을 기록한다. [NIST의 Wilson interval 설명](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)을 따른다. 여러 구간 전체에 대한 동시 신뢰 보장을 주장하지 않는다. 승인 artifact의 선택 결과도 `ELIGIBLE_ADVISORY_ONLY`이며 기존 실행 admission을 대신하지 않는다.

## 원격 증거

- 프로파일·JSON: commit `1c755a7fb35d6ad9b7bbb272f2d461d99779f591`, Model PC 자원 기준 충족, 관련 137 passed / NEW 0.
- v2 CLI·공통 요청: commit `aab682ca6bfff5de79911121f6b1af3753512c12`, Model PC 자원 기준 충족, 관련 145 passed / NEW 0.
- 보정 프로파일 바인딩: commit `ba9c6dffb301e523e7e5901bcdf130dd4cdb934e`, 모델·역할·한도 교체 회귀 8개 RED 이후 관련 82 passed / NEW 0. 이 실행은 자원 하한 미달 fallback이며 지연·용량 수용 증거가 아니다.
- GLM 영속 사용 표식: `5cb1572912`, Model PC 자원 기준 충족, 관련 94 passed / NEW 0. 요청 결과 불명·새 프로세스·다른 사건에서도 첫 실제 호출의 표식을 보존한다.

위 suite는 범위가 겹치므로 합산하지 않는다. 통합 HEAD 시험과 독립 검토 결과는 확인 후 추가한다.

- 통합 `0d006d3122`: 원격 239 passed / exit 0 / NEW 0, `logs/phase3-integrated/run-1.txt`. 자원 하한 미달 fallback이므로 용량·지연 수용은 미확인이다.
- 로컬 어댑터 `eac5ad9ba8`: 여유 확인된 Site PC의 관련 82 passed / exit 0 / NEW 0. 소스의 격리 승인 상수 문제를 RED로 재현하고 기본 수용을 차단했다. 실제 호스트가 검증한 capability를 명시해야 호출할 수 있다.
- 배포 패키지 `79febfdbe2`: v2 모듈의 wheel/sdist 설치·namespace import 및 로컬 제공자 회귀 34 passed / exit 0 / NEW 0, `logs/phase3-delivery/run-1.txt`. 자원 하한 미달 fallback이며 실제 호스트 활성화는 아니다.
- 독립 검토: 프로파일·판정·CLI는 advisory-only 경계에서 중요한 blocker 없음. 로컬 어댑터의 정적 격리 표식은 blocker로 기록하고 수정했다. 최종 수정 및 main 통합은 다시 검토한다.
- 오프라인 실행 `ab100f6b8d`: `tools/decision_calibration.py <frozen-input.json>`은 모델 호출 없이 검수 profile·fit·평가·학습 manifest를 받아 평가 receipt를 출력한다. HOLD/FAIL은 exit 1, PASS_OFFLINE_ONLY만 exit 0이다. 실행기 부재 RED 4개 이후 보정/CLI 34 passed / exit 0 / NEW 0 (`logs/calibration-cli-green/run-1.txt`). 자원 하한 fallback이며 실제 현장 정답은 사용하지 않았다.

## 남은 수용

실제 격리 OpenCode SDK/relay와 GLM 1회 시험, Qwen 직접 v2 호출, 사람이 검수한 독립 현장 데이터와 품질·지연 한계, 실제 Fleet 기준 선택 생산자, 제한된 재관측·결과 readback·최종 사람 인수 연결, Jev/Laya 실제 어댑터, 개선 후보 승격 및 Pinky 현장 수용은 별도로 확인해야 한다. Discord 설정은 담당 세션의 작업이다.
