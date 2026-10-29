# 객체·픽셀 검수 클래스 선택의 공용 부품 이행

2026-10-29, `fix/learning-class-controls`, base `f05af50515`. runtime `b3b265f7e8`, 최종 시험·캡처 `8e084f3e59`(이후 test-only). 클래스 선택을 native button과 화면별 painting에서 기존 ui-button kind=segment/type=button으로 이행했다. 새 부품·토큰·API는 만들지 않았다.

두 선택 집합의 enable selector·disabled·aria-pressed를 함께 바꾸고, custom element에 native value 반사가 없으므로 value attribute를 명시해 생성·비교·픽셀 select 변경에서 같은 값을 읽는다. 객체의 클래스 이름·표시명·신호 상태 기본값·hotkey·edit 저장, 픽셀의 index·데이터 색 swatch·select change·키보드·canvas 복귀와 권한/승인 판단은 유지했다. 클래스 색은 주석 데이터 표현으로 남기며 UI 팔레트로 재해석하지 않았다.

app.css에서 class-chip의 배경·색·테두리·radius·padding·높이·focus·disabled 중복을 제거했다. 배치·간격·가로 스크롤·kbd 보조 글자 역할은 표면에 남긴다. 기존1490줄 객체 browser 파일은 selector3곳만 같은 줄 수로 고쳤고 새32조합은 여유 있는 기존 pixel browser 파일에 추가했다. 회귀 선택·시험 한도를 우회하지 않았다.

## 실행 증거

공식 원격 시험 PC에서 커밋 SHA를 실행했다. 합성 사진·임시 ReviewStore만 사용했으며 실제 라벨·장치·HF에는 접근하지 않았다. 원본 `C:/DevTemp/rosy-ui-standardization/`, 로그5개·최종16PNG hash는 인접 manifests에 고정했다.

| source | 로그 | 결과·의미 |
|---|---|---|
| `c5ce83b15b` | class-controls-red/run-1.txt | 2 실패/70 deselected 중 pixel은 실제 공용 kind 누락, object는 잘못된 descendant locator였음 |
| `b3b265f7e8` | class-controls-green/run-1.txt | 기존 객체·픽셀 browser 두 파일 전체 **220 passed/0 skipped**, 591.20s |
| `8e084f3e59` | class-controls-captures/run-1.txt | 더 강한 실제 다른 픽셀 선택 확인 **32 passed/40 deselected/0 skipped**와16PNG |
| `b3b265f7e8` | class-controls-contracts/run-1.txt | shared controls·UI token·typography **80 passed/0 skipped**, warnings2 |
| `8e084f3e59` | class-controls-affected/run-1.txt | 공식 selector affected/no escalation/5 changed/1 invocation, **2880 passed/384 skipped**, warnings51 |

합격 로그들은 known_failures NEW0/known0/flaky0이다. listed-but-not-failing 테마 항목은 이 범위의 수정 증거가 아니므로 baseline을 유지했다. 220에는 처음32조합이 포함되며 강화32는 같은 부분집합의 재실행이다. 252개의 서로 다른 browser case로 합산하지 않는다. native384 skip에는 opt-in browser가 포함되므로 통과로 세지 않으며, source별 browser 실행과 별도로 기록한다.

최초 object fixture의 locator는 chip 자체 대신 자식을 찾았다. 별도 cbc19289c1에서 즉시 고쳤고 그 실패는 제품 결함으로 세지 않았다. 이후 전체220이 수정된 locator로 통과했다. 최종8e는 처음 이미 선택된 픽셀 대신 다른 값을 택하는 assertion을 강화했으며 runtime은 b3와 같다. 실패 로그는 덮어쓰거나 baseline에 추가하지 않았다.

32조합은 object/pixel × 320/390/768/1440 × dark/light × Enter/Space다. 공용 종류·48px 이상 표적·초기 disabled·키로 선택·pressed·canvas 초점 복귀·가로 넘침을 검사했다. 객체는 선택한 박스만 같은 label을 저장하고 pending/승인 불가를 유지하며, 픽셀은 select만 바꾸고 mask version0을 유지한다. 기존 전체 회귀의 custom class·숫자키·상태/결정 assertion도 유지했다.

## 화면 검토와 범위

최종16장은 Enter 후의 object/pixel × 네 폭 × 두 테마다. job scratch 밖 `/tmp/rosy-class-ui-20261029-first`에서 `C:/DevTemp/rosy-ui-standardization/class-captures-final/`로 복사했다. A(`/root/ui_design`) 소스 검토와 독립 B(`/root/ui_evidence`)의16/16장 직접 검토에서 해당 변경의 P1/P2가 없었다. Root도 320 밝게 object·1440 어둡게 pixel을 직접 봤다.

선택된 장애물 상자/벽이 공통 중립 채움으로 구별되고 데이터 색·숫자 키·승인 대기 사유가 유지된다. 320/390은 도구가 접히며 캔버스·리본과 겹치지 않는다. 일부 모바일 클래스는 가로 스크롤 밖이며, 정지 이미지가 모든 클래스의 키보드/스크롤 도달성이나 아래 결정 패널 전체를 증명하지 않는다. Enter/Space 동작은 실행 assertion의 근거다.

SOURCE/LOCAL/device/field gate를 올리지 않는다. 전체 플랫폼 UI·조합된 이전 UI 브랜치·native 빌드·실물/실제 사람 라벨·모델 품질·배포/착지/push/merge 수용과 구분한다. 최종 통합과 나머지 표면 이행은 별도다.

CE: 해당 없음 — 부품의 value/disabled/pressed 연결과 데이터/승인 경계는 최종 코드·실제 store/키보드 회귀·이 기록에서 복구할 수 있다. 일반 부품 이행을 별도 교훈으로 중복하지 않았다.
