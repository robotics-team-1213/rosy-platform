# D-704 Pinky 최종 속도 원본의 평면 축 검증

**Status:** Accepted (2026-10-12, source contract)

Pinky Episode는 기록된 CORE 최종 Twist의 linear.x(m/s)와 angular.z(rad/s)를 사용하는 2축 자료다. 원본 MCAP에서 Twist 여섯 축 모두 유한한 숫자인지 확인하고, 나머지 네 축은 0이어야 한다. 다른 축의 움직임이나 NaN/Infinity를 버리거나 null/0으로 보간하지 않고 원본 검증을 거절한다. 허용 축의 부호·값·시각·namespace와 기존 원본 hash 검증은 유지한다.

D-427의 curation/raw verifier가 자료를 검증하며 D-429의 기존 decoder를 재사용한다. D-430의 CORE 최종 writer 권한이나 동작 제한을 바꾸지 않는다. 다른 로봇의 다축 자료를 이 평면 Episode로 수용하지 않는다.

최종 속도 기록은 모델의 불필요 개입 여부를 단독으로 입증하지 않는다. 정상 주행과 모델 개입의 원인·시도·사건·admission을 별도로 결속해야 한다. 원본 CRC/hash·시각·topic 검증도 모든 메시지 수집·publisher 인증·무누락·정상 상태 무명령·재발 0건과 동의어가 아니다. 전체 운영 coverage와 독립 수용은 후속이며 기존 비교의 미확인 수치는 null/HOLD를 유지한다.
