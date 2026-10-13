# D-701 실제 규칙 선택의 독립 비교 export

**Status:** Accepted (2026-10-12, source contract)

D-700의 선택 원장을 기존 curation owner에서 read-only SQLite snapshot으로 내보낸다. subject·case(정상은 null)·owner·rule config·necessity policy·시작/끝을 명시하고 최대 24시간·4,096행·1MiB JSON으로 제한한다. row ID·수신 시각·원래 receipt hash와 scope를 재검증한다. 누락·변조·다른 사건/설정은 거절하며 retention 밖 자료를 만들지 않는다.

기존 operational_cohort/1과 모델 export는 유지한다. 선택적 /2는 같은 evaluation 사건 집합의 실제 규칙 export를 별도 rules 후보로 결속한다. 규칙에 가짜 ModelProfile·모델 시도·예산·비용 0을 넣지 않는다. MIXED 자료는 rule-only 기준으로 거절한다. selection과 necessity 건수만 보고하고 실행/성공·명령/모델 호출·재발·청구는 null이다. 선택 기준과 전체 운영 기준을 구분하며 독립 정답·coverage·map/lifecycle/code provenance 수용 전 HOLD를 유지한다.

| 기존 계약 | 관계 |
|---|---|
| D-427 | Fleet은 실제 원장, curation은 고정 export, 독립 evaluation은 비교를 소유한다. learning→operations runtime import 없음. |
| D-429 | 기존 원장·stdlib/contracts JSON 검증을 재사용하며 별도 서비스·writer·wheel을 만들지 않는다. |
| D-430 | 선택/비교는 command admission과 독립 품질 승격이 아니다. CORE 최종 권한을 유지한다. |

실제 생산 원장→export→기존 모델 export와 동일 cohort→독립 CLI를 시험한다. 잘린 범위·다른 사건·MIXED·hash/ID/clock/config 변경·학습/보정/평가 누출과 기존 /1 회귀를 검사한다. source·remote와 실제 모델·운영/현장 수용은 별도다.
