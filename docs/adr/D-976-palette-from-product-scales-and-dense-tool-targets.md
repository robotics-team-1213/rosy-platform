## D-976 팔레트 값은 실제 제품 색 체계의 단계에서 고르고, 넓은 화면 도구는 36px 단계를 쓴다 — D-82 값 출처·D-629 크기 규칙 개정

**Status:** Accepted (2026-11-04, 사용자 결정: 「그렇게 처리해」 — 제안 팔레트 저장소 반영과 밀도 토큰 두 개 승인). D-82의 의미 집합과 게이트는 그대로 두고 값의 출처를 바꾼다. D-629 「모든 버튼 48px」에 넓은 화면 도구 단계를 더한다.

잇는 결정: [D-82](D-82-oklch.md)(의미 집합) · [D-629](D-629-control-sizing-and-console-hierarchy.md)(조작 크기) · [D-202](D-202-danger-is-a-fill-alarm-text-contrast-contract.md)(위험은 채움) · [D-214](D-214-text-contrast-floor.md)(글자 대비) · [D-277](D-277-rosy-brand-colour-tokens.md)(장미색) · [D-975](D-975-line-map-stage-track-and-app-lines.md)(앱 노선)

### Context

- 노선도 시안(Design 캔버스 「ROSY 노선도 재디자인」)을 본 사용자가 색이 「너무 부자연스럽다」고 했다(2026-11-04). 값마다 따로 생성한 색이 비슷한 높은 채도로 차가운 남색 바탕 위에 모였다.
- 사용자는 다른 사이트의 실제 팔레트를 찾아 개선하라고 했고, 화면 밀도를 높이라고 했다. 밀도에는 48px 고정 단추가 걸린다(D-629).
- taste-skill(design-taste-frontend)의 작업 화면 연구는 색을 화면의 약 3%에, 데이터와 상태에만 둔다.

### Decision

1. **값의 출처.** 무채색은 Radix Colors slate, 상태·계열·앱 노선·장미색은 Radix Colors와 GitHub Primer의 단계에서 고른다. 어두운 페이지 바탕은 taste-skill이 모니터용으로 권하는 차가운 근흑(#0c0d0f)과 slate 1을 쓴다. tokens.css 각 줄 주석이 출처다.
2. **바꾸지 않는 것.** 팔레트 키 집합·의미 집합·파생·역할·`test_palette_gates.py`의 모든 기준. `ink`·`ink-on-crit`은 `#eeeeef` 그대로다(slate 12 `#edeef0`와 사실상 같고 사본 변경을 줄인다).
3. **기록한 값.** 어둡게: ground `#111113`·deep `#0c0d0f`, 위험 `#b54548`(Radix red 8), 주의 `#ffc53d`(Radix amber 9), 계열 `#58a6ff`(Primer)·`#2870bd`(Radix blue 8), 좋음·목표 `#3dd68c`(Radix green 11), 노선 `#0eb39e`·`#9eb1ff`·`#b1a9ff`, 장미 `#e796f3`(Radix plum 11). 밝게: ground `#f9f9fb`, 위험 `#82071e`, 주의 `#bc4c00`(Primer 주황), 계열 `#0d74ce`·`#0d419d`, 노선 `#107d98`·`#5753c6`·`#6550b9`, 장미 `#bb42a4`. 로봇 사다리는 계열 파랑의 색상으로 밝기만 바꾼다.
4. **밝게 주의는 주황이다.** 빨강 쪽 주의(`#d13415`)는 밝은 화면에서 「지연」이 오류처럼 읽혔다(캔버스 렌더 관측). 주황(H 45)은 위험과 색약 대비 2.03을 지킨다.
5. **색의 면적.** 같은 색이 넓은 면을 칠하지 않는다. 끝난 진행·정상 칸은 중립이고, 색은 지금 도는 것과 주의가 필요한 것에만 둔다(DESIGN.md 「색」).
6. **도구 단계.** `--target-tool` 36px(도구 막대·표 행 동작의 아이콘 단추)와 `--row-dense` 34px(표·목록 행)를 둔다. 넓은 화면(64rem 이상) 마우스 작업 면에서만 쓰고, 64rem 미만에서는 소비 시트가 `--target-secondary`로 되돌린다. 주 동작·비상 정지·되돌릴 수 없는 조작·폼 입력은 48px 그대로다.
7. **사본.** 정적 theme-color(6개 문서)·Pilot PWA 매니페스트·Android 런처 바탕·앱 아이콘 SVG·로봇 얼굴 LCD 색 튜플을 같은 변경에서 맞춘다. Android 토큰은 빌드 때 tokens.css에서 생성한다.

### Consequences

- 팔레트 게이트(로컬 39개)는 두 테마에서 통과한다. 원격 affected 시험으로 사본·브라우저 시험을 확인한다.
- 로봇 얼굴 LCD의 색이 바뀐다. 실물 LCD 판독(1.5m·0.5초)은 DEVICE 관측으로 따로 확인해야 하며 이 결정이 수용을 뜻하지 않는다.
- 도구 단계 토큰은 아직 소비하는 화면이 없다. 화면 적용(D-975 P2 이후)에서 소비 시트와 64rem 되돌림을 함께 넣는다.
- 밝게는 여전히 운용 권장 테마가 아니다(D-359).
