# perception_evaluation verification log

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

## 2026-10-11 · b64dc94e0a · D-665 기준점 기반 구역 로직과 별도 인지 평가

- 변경: 명시적 관측 기준점과 World 입력 유효성을 사용해 현재 구역을 산출하고 도로면/구역 정답을 따로 점수화한다. 중앙/최대 영역 대체·목적지 가지 선택·가림 채우기는 하지 않는다.
- 증거: b64dc94e0a 원격 합성 로직·기존 기준선·World 설치 wheel 35 passed, terminal exit 0, known_failures NEW 0. 시각 불일치·잘못된 정답·invalid image의 미평가 분모도 확인했다.
- gate 변화: 없음. 실제 투영 입력 생산자·독립 정답·coverage·장치 관측 전달은 미완료다.
- 결정: D-665

