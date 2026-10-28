## D-902 Pilot real OMX teleop and recording through Fleet and the CORE manual arm path

**Status:** Proposed (2026-10-28, 사용자 지시로 방향 초안). 실물 OMX를 Pilot에서 조종·녹화하는 소유 경로를 정한다. 구현·배포·실물 동작·DEVICE/FIELD 수용을 뜻하지 않는다. D-894 계약 착지와 런타임 수용 뒤에만 구현 단계로 간다.

### Context

Pilot의 팔 화면은 `drivers/omx_sim.js`만 있다. D-390이 실물 OMX 프로필을 `enabled: false`로 두고 Gazebo 연습만 수용했고, D-411의 녹화도 실물 OMX는 시뮬레이션만 범위로 했다. 그동안 실물 팔 S는 관제 PC에서 `record_session.py`·`chunk_runner`를 SSH와 명령 FIFO로 조작하고, 리더 녹화(D-846·D-848)도 CLI로만 돈다. 사용자는 이 조작·녹화를 ROSY 제품 화면에서 하기를 원한다.

D-894가 실물 팔 수동 조작의 계약을 정했다: Fleet 인증 세션 → 인증된 CORE → 같은 호스트 UDS → OMX 단일 owner, 브라우저는 Fleet origin만 부른다, jog/park/goto/run만, 0.25 s deadman, Pilot·Action 배타. Pilot은 지금 장치가 같은 origin에서 정적 자산과 API를 함께 제공하는 구조(D-323·D-365·D-390)라, 실물 OMX에 그대로 쓰면 D-894의 Fleet-origin 규칙과 맞지 않는다.

### Decision

1. **실물 OMX Pilot은 Fleet origin에서 제공한다.** Fleet이 기존 Pilot 정적 자산을 자기 origin 아래에서 내려 주고, 실물 팔 드라이버(`drivers/omx_manual.js`)는 Fleet의 D-894 수동 조작 경로만 부른다. 장치 HTTP API, 시뮬레이션 `pilot_sim` 엔드포인트, FIFO, serial에 브라우저가 닿는 경로는 만들지 않는다. Pinky와 OMX 시뮬레이션의 장치-origin Pilot(D-390)은 그대로 둔다.
2. **조종은 D-894 seat와 deadman을 그대로 쓴다.** Pilot의 팔 스틱·관절 조그는 D-894의 jog(관절 하나, 0.05 rad 이하, 넘으면 거절)로, park/goto/run은 같은 이름의 typed 명령으로만 보낸다. 누르고 있는 동안만 움직이고, Pilot 화면의 keepalive가 D-894 presence다. Pilot 전용 권한·seat·속도 한계를 새로 두지 않는다(D-460의 seat 계약 금지와 같은 방향). 정지 버튼은 seat 없이도 D-894 stop을 부른다.
3. **드라이버 등록은 D-366 규칙을 따른다.** `drivers/registry.js`에 실물 OMX 종류 하나를 더하고, 화면은 D-894 상태가 광고한 관절·chunk·reason만 그린다. 시뮬레이션과 실물은 장치 종류·capability·배포 프로필이 다르다(D-390 §5 유지). 실물 화면은 항상 "실물" 표시를 하고, 시뮬레이션 화면을 실물로 재사용하지 않는다.
4. **녹화는 조종과 다른 owner다.** 녹화 시작·정지는 Fleet → CORE 요청으로 받고, 기록은 OMX 쪽 기존 수집 owner(`record_session`/리더 녹화 계보 D-848)가 한다. 녹화는 증거이며 제어 경로가 읽지 않는다(D-411 A.1과 같은 원칙). Pilot 조작 세션의 원 입력·수락 여부·주체를 `teleop/intent`와 같은 형태로 함께 남긴다(D-411 A.2). 녹화 한계(1회 길이, 동시 1개, 쿼터)와 정지 중 수신은 D-411·D-534를 따른다.
5. **실행 중인 수집 세션을 빼앗지 않는다.** `record_session`·`chunk_runner`가 버스를 쥐고 있으면 Pilot은 관측과 정지만 할 수 있다. 넘겨받기는 D-894의 배타·명시적 rearm 절차로만 하고, 자동 종료나 자동 인계는 하지 않는다.
6. **순서.** (a) D-894 계약 착지 → (b) D-894 CORE·UDS·owner 런타임과 양 끝 시험 → (c) Fleet의 Pilot 자산 제공과 `omx_manual` 드라이버(조그·정지만) → (d) 녹화 연결 → (e) 사람 입회 실물 확인. 각 단계는 따로 착지하고, (c)부터는 안전 경로로 혼자 착지한다(D-889).

### Relationship to existing decisions

| Decision | Relationship |
|---|---|
| D-390 | 시뮬레이션 연습 경계는 유지. 실물 프로필은 이 ADR의 경로로만 연다. |
| D-411 / D-534 | 녹화 소유·내용·한계·수신 원칙을 실물 OMX에 그대로 적용. "실물 OMX는 시뮬레이션만" 범위 제한은 이 ADR이 수용되고 구현이 검증될 때 넓힌다. |
| D-366 | 드라이버 추가 규칙 그대로. |
| D-460 | Pilot 전용 seat 계약을 만들지 않는다. 실물 팔 seat는 D-894 것이다. |
| D-846 / D-848 | 리더 구동·녹화 계보 유지. Pilot 녹화도 같은 계보 기록을 쓴다. |
| D-894 | 유일한 조종 경로. 이 ADR은 그 위의 화면·녹화 연결만 정한다. |
| D-901 | 관측(영상·관절)은 D-901의 같은 호스트 스냅샷에서 Fleet으로 온 것을 쓴다. 원본 영상은 호스트 밖으로 나가지 않는다(D-795). |

### Consequences

- Pilot 하나로 Pinky·OMX 시뮬레이션·실물 OMX를 조종하지만, 실물 OMX만 Fleet을 거친다. 두 origin을 쓰는 설치·안내가 필요하다.
- 실물 팔 조작 권한·정지·재개 판단이 D-894 한 곳에 모인다. Pilot은 화면일 뿐 권한을 갖지 않는다.
- 이 ADR만으로 실물 팔은 움직이지 않는다. 각 구현 단계는 원격 시험, 독립 안전 검토, 사람 입회 실물 확인을 따로 거친다.
